"""Sensors for the Nee-Vo Tank Monitor integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPressure, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import NeeVoConfigEntry, NeeVoCoordinator, TankData
from .entity import NeeVoEntity

PARALLEL_UPDATES = 0

PRESSURE_UNITS = {
    "psi": UnitOfPressure.PSI,
    "psig": UnitOfPressure.PSI,
    "kpa": UnitOfPressure.KPA,
    "bar": UnitOfPressure.BAR,
    "mbar": UnitOfPressure.MBAR,
    "hpa": UnitOfPressure.HPA,
}


@dataclass(frozen=True, kw_only=True)
class NeeVoSensorDescription(SensorEntityDescription):
    """Describes one tank sensor."""

    value_fn: Callable[[TankData], StateType | datetime]
    exists_fn: Callable[[TankData], bool] = lambda _: True


SENSORS: tuple[NeeVoSensorDescription, ...] = (
    NeeVoSensorDescription(
        key="level",
        translation_key="level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda tank: tank.level_pct,
    ),
    NeeVoSensorDescription(
        key="remaining",
        translation_key="remaining",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda tank: tank.remaining_l,
    ),
    NeeVoSensorDescription(
        key="consumed",
        translation_key="consumed",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda tank: tank.consumed_l,
    ),
    NeeVoSensorDescription(
        key="consumption_rate",
        translation_key="consumption_rate",
        native_unit_of_measurement="L/d",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda tank: tank.rate_l_per_day,
    ),
    NeeVoSensorDescription(
        key="days_remaining",
        translation_key="days_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda tank: tank.days_remaining,
    ),
    NeeVoSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda tank: tank.last_reading,
    ),
    NeeVoSensorDescription(
        key="last_refill",
        translation_key="last_refill",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda tank: tank.last_refill,
    ),
    NeeVoSensorDescription(
        key="capacity",
        translation_key="capacity",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda tank: tank.capacity_l,
    ),
    NeeVoSensorDescription(
        key="pressure",
        translation_key="pressure",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda tank: tank.pressure,
        exists_fn=lambda tank: tank.pressure is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeeVoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensors for each tank, including tanks added to the account later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new_tanks() -> None:
        new = set(coordinator.data) - known
        known.update(new)
        async_add_entities(
            NeeVoSensor(coordinator, tank_id, description)
            for tank_id in new
            for description in SENSORS
            if description.exists_fn(coordinator.data[tank_id])
        )

    add_new_tanks()
    entry.async_on_unload(coordinator.async_add_listener(add_new_tanks))


class NeeVoSensor(NeeVoEntity, SensorEntity):
    """One tank sensor."""

    entity_description: NeeVoSensorDescription

    def __init__(
        self,
        coordinator: NeeVoCoordinator,
        tank_id: str,
        description: NeeVoSensorDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, tank_id, description.key)
        self.entity_description = description
        if description.key == "pressure":
            unit = PRESSURE_UNITS.get((self.tank.pressure_unit or "").strip().lower())
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class = SensorDeviceClass.PRESSURE if unit else None

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor's value."""
        return self.entity_description.value_fn(self.tank)
