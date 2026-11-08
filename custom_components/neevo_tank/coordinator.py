"""Fetch tank data for the Nee-Vo Tank Monitor integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from math import isfinite
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FAILURE_GRACE,
    HISTORY_FRESH_FOR,
    RATE_MINIMUM_DAYS,
    RATE_WINDOW_DAYS,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)
from .meter import MeterState, advance, consumed_over, start_meter
from .pyneevo import LevelReading, NeeVoApiInterface, Tank
from .pyneevo.errors import InvalidCredentialsError, PyNeeVoError

_LOGGER = logging.getLogger(__name__)

type NeeVoConfigEntry = ConfigEntry[NeeVoCoordinator]


@dataclass
class TankData:
    """One tank's values for one update."""

    tank_id: str
    name: str | None
    serial: str | None
    level_pct: float | None
    capacity_l: float | None
    remaining_l: float | None
    consumed_l: float
    rate_l_per_day: float | None
    days_remaining: float | None
    last_reading: datetime | None
    last_refill: datetime | None
    pressure: float | None
    pressure_unit: str | None
    raw: dict[str, Any]


def _number(value: Any) -> float | None:
    """Return a finite number as a float, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _parse_date(value: Any) -> datetime | None:
    """Read a stored date, tolerating a damaged storage file."""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _load_meter(stored: Any) -> MeterState | None:
    """Rebuild a meter from storage, or None if it cannot be trusted."""
    if not isinstance(stored, dict):
        return None
    total = _number(stored.get("total_l"))
    watermark = _number(stored.get("watermark_pct"))
    last_date = _parse_date(stored.get("last_date"))
    if total is None or total < 0 or watermark is None or last_date is None:
        return None
    return MeterState(total, watermark, last_date, _parse_date(stored.get("last_refill")))


def _dump_meter(meter: MeterState) -> dict[str, Any]:
    """Convert a meter to something storage can save."""
    return {
        "total_l": meter.total_l,
        "watermark_pct": meter.watermark_pct,
        "last_date": meter.last_date.isoformat() if meter.last_date else None,
        "last_refill": meter.last_refill.isoformat() if meter.last_refill else None,
    }


class NeeVoCoordinator(DataUpdateCoordinator[dict[str, TankData]]):
    """Poll the Nee-Vo service for every tank on the account."""

    config_entry: NeeVoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: NeeVoConfigEntry,
        api: NeeVoApiInterface,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry.entry_id}"
        )
        self._meters: dict[str, MeterState] = {}
        self._last_success: datetime | None = None
        self.first_failure: datetime | None = None

    @property
    def _issue_id(self) -> str:
        """Return the repair issue ID for this config entry."""
        return f"cloud_unreachable_{self.config_entry.entry_id}"

    async def async_load_meters(self) -> None:
        """Load saved meters, so totals carry on across restarts."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        for tank_id, value in stored.items():
            if (meter := _load_meter(value)) is not None:
                self._meters[tank_id] = meter

    def _dump_meters(self) -> dict[str, Any]:
        """Return all meters in a form storage can save."""
        return {tank_id: _dump_meter(meter) for tank_id, meter in self._meters.items()}

    async def async_save_meters(self) -> None:
        """Save meters now."""
        await self._store.async_save(self._dump_meters())

    async def _async_update_data(self) -> dict[str, TankData]:
        """Fetch every tank."""
        try:
            await self.api.refresh_tanks()
            tanks: dict[str, Tank] = await self.api.get_tanks_info()
            if not tanks:
                raise PyNeeVoError("No tanks returned")
            histories = {
                tank_id: await self._async_history(tank_id) for tank_id in tanks
            }
        except InvalidCredentialsError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except PyNeeVoError as err:
            return self._handle_failure(err)

        now = dt_util.utcnow()
        data = {
            tank_id: self._build(tank, histories[tank_id], now)
            for tank_id, tank in tanks.items()
        }
        self._last_success = now
        self.first_failure = None
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
        self._store.async_delay_save(self._dump_meters, STORAGE_SAVE_DELAY)
        return data

    async def _async_history(self, tank_id: str) -> list[LevelReading]:
        """Fetch a tank's history, which is optional for the rest of the update."""
        try:
            return await self.api.get_level_history(tank_id)
        except InvalidCredentialsError:
            raise
        except PyNeeVoError as err:
            _LOGGER.debug("Level history unavailable: %s", type(err).__name__)
            return []

    def _handle_failure(self, err: PyNeeVoError) -> dict[str, TankData]:
        """Keep the last good data through a short outage, then report it."""
        now = dt_util.utcnow()
        reason = type(err).__name__
        if self.first_failure is None:
            self.first_failure = now
            _LOGGER.warning("Could not update Nee-Vo tanks: %s", reason)

        if now - self.first_failure >= FAILURE_GRACE:
            # Forum users have seen rejected passwords reported as HTTP 502, so
            # this asks the user to check, rather than assuming a bad password.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="cloud_unreachable",
            )

        if (
            self.data
            and self._last_success is not None
            and now - self._last_success < FAILURE_GRACE
        ):
            return self.data

        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": reason},
        ) from err

    def _build(
        self, tank: Tank, history: list[LevelReading], now: datetime
    ) -> TankData:
        """Turn one tank's raw data into its sensor values."""
        capacity = _number(tank.tank_capacity)
        if capacity is not None and capacity <= 0:
            capacity = None

        readings = [
            (reading.date, level)
            for reading in history
            if (level := _number(reading.level)) is not None
        ]
        meter = self._meters.get(tank.id)
        if meter is None:
            if readings:
                meter = self._meters[tank.id] = start_meter(readings)
        else:
            advance(meter, readings, capacity)

        level = _number(tank.level)
        if readings and now - readings[-1][0] <= HISTORY_FRESH_FOR:
            level = readings[-1][1]  # History has decimals; the tank list does not.
        if level is not None and not 0 <= level <= 100:
            level = None

        remaining = None
        if level is not None and capacity is not None:
            remaining = round(level / 100 * capacity, 1)

        rate = self._rate(readings, capacity, now)
        days_remaining = None
        if rate and remaining is not None:
            days_remaining = round(remaining / rate)

        serial = tank.serial_number
        return TankData(
            tank_id=tank.id,
            name=tank.name,
            serial=str(serial) if serial is not None else None,
            level_pct=level,
            capacity_l=capacity,
            remaining_l=remaining,
            consumed_l=round(meter.total_l, 1) if meter else 0.0,
            rate_l_per_day=rate,
            days_remaining=days_remaining,
            last_reading=tank.last_reading,
            last_refill=meter.last_refill if meter else None,
            pressure=_number(tank.tank_last_pressure),
            pressure_unit=tank.tank_last_pressure_unit,
            raw=tank.data,
        )

    @staticmethod
    def _rate(
        readings: list[tuple[datetime, float]],
        capacity: float | None,
        now: datetime,
    ) -> float | None:
        """Return the average liters per day over the recent window."""
        window = [
            reading
            for reading in readings
            if reading[0] >= now - timedelta(days=RATE_WINDOW_DAYS)
        ]
        if capacity is None or len(window) < 2:
            return None
        span = (window[-1][0] - window[0][0]).total_seconds() / 86400
        if span < RATE_MINIMUM_DAYS:
            return None
        return round(consumed_over(window, capacity) / span, 2)
