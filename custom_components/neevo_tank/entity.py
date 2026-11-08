"""Base entity for the Nee-Vo Tank Monitor integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import NeeVoCoordinator, TankData


class NeeVoEntity(CoordinatorEntity[NeeVoCoordinator]):
    """An entity belonging to one tank."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NeeVoCoordinator, tank_id: str, key: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._tank_id = tank_id
        self._attr_unique_id = f"{tank_id}_{key}"
        tank = coordinator.data[tank_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tank_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=tank.name or MODEL,
            serial_number=tank.serial,
        )

    @property
    def tank(self) -> TankData:
        """Return this tank's current values."""
        return self.coordinator.data[self._tank_id]

    @property
    def available(self) -> bool:
        """Return False if the update failed or the tank left the account."""
        return super().available and self._tank_id in self.coordinator.data
