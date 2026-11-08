"""Binary sensors for the Nee-Vo Tank Monitor integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import READING_OVERDUE_AFTER
from .coordinator import NeeVoConfigEntry, NeeVoCoordinator
from .entity import NeeVoEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeeVoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a binary sensor for each tank, including tanks added later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new_tanks() -> None:
        new = set(coordinator.data) - known
        known.update(new)
        async_add_entities(
            NeeVoReadingOverdue(coordinator, tank_id) for tank_id in new
        )

    add_new_tanks()
    entry.async_on_unload(coordinator.async_add_listener(add_new_tanks))


class NeeVoReadingOverdue(NeeVoEntity, BinarySensorEntity):
    """On when the monitor has not reported for too long."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "reading_overdue"

    def __init__(self, coordinator: NeeVoCoordinator, tank_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator, tank_id, "reading_overdue")

    @property
    def is_on(self) -> bool | None:
        """Return whether the last reading is overdue."""
        last_reading = self.tank.last_reading
        if last_reading is None:
            return None
        return dt_util.utcnow() - last_reading > READING_OVERDUE_AFTER
