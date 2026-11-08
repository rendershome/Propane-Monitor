"""Diagnostics for the Nee-Vo Tank Monitor integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import NeeVoConfigEntry

# Diagnostics get shared publicly, and the API can add fields without warning, so
# anything identifying is removed, including who supplies the propane.
TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "tank_id",
    "name",
    "serial",
    "Id",
    "CustomName",
    "SerialNumber",
    "Latitude",
    "Longitude",
    "CompanyId",
    "CompanyImageId",
    "CompanyName",
    "CompanySupportPhoneNumber",
    "DealerId",
    "ImageId",
    "FirstName",
    "LastName",
    "Address",
    "Address2",
    "PhoneNumber",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NeeVoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with private details removed."""
    coordinator = entry.runtime_data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "failing_since": coordinator.first_failure,
        "tanks": [
            async_redact_data(asdict(tank), TO_REDACT)
            for tank in coordinator.data.values()
        ],
    }
