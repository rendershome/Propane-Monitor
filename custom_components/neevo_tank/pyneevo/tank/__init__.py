"""Define Nee-Vo tank classes."""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, NamedTuple, Optional

_LOGGER = logging.getLogger(__name__)

# .NET JSON date: epoch milliseconds (absolute UTC) plus an optional display
# offset that does not change the instant.
_NET_DATE = re.compile(r"/Date\((-?\d+)(?:[-+]\d{4})?\)/")


def parse_net_date(value: Any) -> Optional[datetime]:
    """Convert a .NET JSON date to a UTC datetime, or ``None`` if it is invalid."""
    if not isinstance(value, str):
        return None
    match = _NET_DATE.fullmatch(value)
    if match is None:
        return None
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, timezone.utc)
    except (OverflowError, ValueError, OSError):
        return None


class LevelReading(NamedTuple):
    """One entry from a tank's level history."""

    date: datetime
    level: Optional[float]
    consumption: Optional[float]


class Tank:
    """Define a Nee-Vo tank.

    Optional properties return ``None`` when the API omits the field, so one
    renamed field cannot crash the code reading the others.
    """

    def __init__(self, tank_data: dict, api_interface: Any) -> None:
        """Initialize."""
        self._api_interface = api_interface
        self._tank_data = tank_data
        self._update_callback: Optional[Callable[[], None]] = None

    def set_update_callback(self, callback: Callable[[], None]) -> None:
        """Set a function to call whenever this tank's data is replaced."""
        self._update_callback = callback

    def _update_tank_info(self, update: dict) -> None:
        """Replace this tank's data with a newer record for the same tank.

        Replacing rather than merging means a field the API stops sending
        disappears instead of keeping its last value and looking current.
        """
        if update.get("Id") != self.id:
            _LOGGER.debug("Ignoring an update meant for a different tank")
            return

        self._tank_data = update
        if self._update_callback is not None:
            self._update_callback()

    def _first_value(self, *keys: str) -> Any:
        """Return the first non-null value among possible field names."""
        for key in keys:
            value = self._tank_data.get(key)
            if value is not None:
                return value
        return None

    @property
    def id(self) -> Any:
        """Return the ID of the tank."""
        return self._tank_data["Id"]

    @property
    def name(self) -> Optional[str]:
        """Return the name of the tank."""
        return self._tank_data.get("CustomName")

    @property
    def product(self) -> Optional[str]:
        """Return the product type of the tank."""
        return self._first_value("Product", "product")

    @property
    def data(self) -> dict:
        """Return the raw data of the tank."""
        return self._tank_data

    @property
    def level(self) -> Any:
        """Return the fill level of the tank in percent."""
        return self._first_value("CurrentLevel", "Level")

    @property
    def serial_number(self) -> Any:
        """Return the serial number of the tank."""
        return self._tank_data.get("SerialNumber")

    @property
    def tank_capacity(self) -> Any:
        """Return the capacity of the tank."""
        return self._tank_data.get("TankCapacity")

    @property
    def tank_last_pressure(self) -> Any:
        """Return the last reported pressure of the tank."""
        return self._tank_data.get("TankLastPressure")

    @property
    def tank_last_pressure_unit(self) -> Optional[str]:
        """Return the unit of the last reported pressure."""
        return self._tank_data.get("TankPressureDisplayUnitSymbol")

    @property
    def last_reading(self) -> Optional[datetime]:
        """Return when the monitor last reported, in UTC, or ``None`` if unknown."""
        return parse_net_date(self._tank_data.get("LastReadingDate"))

    @property
    def latitude(self) -> Optional[float]:
        """Return the tank's latitude. This is private: do not log or share it."""
        return self._tank_data.get("Latitude")

    @property
    def longitude(self) -> Optional[float]:
        """Return the tank's longitude. This is private: do not log or share it."""
        return self._tank_data.get("Longitude")

    @property
    def company_id(self) -> Optional[str]:
        """Return the ID of the propane company."""
        return self._tank_data.get("CompanyId")

    @property
    def dealer_id(self) -> Optional[str]:
        """Return the ID of the propane dealer."""
        return self._tank_data.get("DealerId")

    @property
    def company_image_id(self) -> Optional[str]:
        """Return the ID of the propane company's image."""
        return self._tank_data.get("CompanyImageId")

    @property
    def company_name(self) -> Optional[str]:
        """Return the name of the propane company."""
        return self._tank_data.get("CompanyName")

    @property
    def company_support_phone_number(self) -> Optional[str]:
        """Return the support phone number of the propane company."""
        return self._tank_data.get("CompanySupportPhoneNumber")

    @property
    def fill_request_available(self) -> Optional[bool]:
        """Return whether the company accepts fill requests through the app."""
        return self._tank_data.get("CompanyFillRequestAvailable")

    @property
    def notify_at_1(self) -> Any:
        """Return the first alert level."""
        return self._tank_data.get("NotifyAt1")

    @property
    def notify_at_2(self) -> Any:
        """Return the second alert level."""
        return self._tank_data.get("NotifyAt2")

    @property
    def notify_critical_levels(self) -> Optional[bool]:
        """Return the NotifyCriticalLevels setting."""
        return self._tank_data.get("NotifyCriticalLevels")

    @property
    def notify_dispatch(self) -> Optional[bool]:
        """Return the NotifyDispatch setting."""
        return self._tank_data.get("NotifyDispatch")

    @property
    def notify_dispatch_enabled(self) -> Optional[bool]:
        """Return the NotifyDispatchEnabled setting."""
        return self._tank_data.get("NotifyDispatchEnabled")

    @property
    def notify_fill_detection(self) -> Optional[bool]:
        """Return the NotifyFillDetection setting."""
        return self._tank_data.get("NotifyFillDetection")

    @property
    def is_owner(self) -> Optional[bool]:
        """Return whether the signed-in account owns this tank."""
        return self._tank_data.get("IsOwner")

    @property
    def consumption_graph_enabled(self) -> Optional[bool]:
        """Return the IsConsumptionVolumeGraphEnabled setting."""
        return self._tank_data.get("IsConsumptionVolumeGraphEnabled")

    @property
    def sensor_min_level(self) -> Any:
        """Return the SensorMinLevel value."""
        return self._tank_data.get("SensorMinLevel")

    @property
    def sensor_max_level(self) -> Any:
        """Return the SensorMaxLevel value."""
        return self._tank_data.get("SensorMaxLevel")

    @property
    def tank_form_type(self) -> Any:
        """Return the TankFormType code, whose meaning is undocumented."""
        return self._tank_data.get("TankFormType")

    @property
    def tank_primary_value_type(self) -> Any:
        """Return the TankPrimaryValueType code, whose meaning is undocumented."""
        return self._tank_data.get("TankPrimaryValueType")

    @property
    def theme_info(self) -> Optional[dict]:
        """Return the app color theme record."""
        return self._tank_data.get("ThemeInfo")
