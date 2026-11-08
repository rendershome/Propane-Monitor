"""The Nee-Vo Tank Monitor integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from . import backoff
from .const import DOMAIN, STORAGE_VERSION
from .coordinator import NeeVoConfigEntry, NeeVoCoordinator
from .pyneevo import NeeVoApiInterface
from .pyneevo.errors import InvalidCredentialsError, PyNeeVoError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: NeeVoConfigEntry) -> bool:
    """Set up a Nee-Vo account."""
    if backoff.should_wait(hass, entry.entry_id):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="waiting_to_retry"
        )

    try:
        api = await NeeVoApiInterface.login(
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
            session=async_get_clientsession(hass),
        )
    except InvalidCredentialsError as err:
        backoff.clear(hass, entry.entry_id)
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except PyNeeVoError as err:
        backoff.record_failure(hass, entry.entry_id)
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": type(err).__name__},
        ) from err

    if api.must_change_password:
        _LOGGER.warning("Nee-Vo says this account's password must be changed")

    coordinator = NeeVoCoordinator(hass, entry, api)
    await coordinator.async_load_meters()
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        backoff.record_failure(hass, entry.entry_id)
        raise
    except ConfigEntryAuthFailed:
        backoff.clear(hass, entry.entry_id)
        raise

    backoff.clear(hass, entry.entry_id)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeeVoConfigEntry) -> bool:
    """Unload a Nee-Vo account, saving its meters."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_save_meters()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: NeeVoConfigEntry) -> None:
    """Remove saved meters and any repair issue when an account is deleted."""
    backoff.clear(hass, entry.entry_id)
    store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    await store.async_remove()
    ir.async_delete_issue(hass, DOMAIN, f"cloud_unreachable_{entry.entry_id}")
