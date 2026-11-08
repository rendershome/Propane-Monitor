"""Sign-in screens for the Nee-Vo Tank Monitor integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .const import DOMAIN
from .pyneevo import NeeVoApiInterface
from .pyneevo.errors import InvalidCredentialsError, PyNeeVoError

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def _async_validate(hass: HomeAssistant, email: str, password: str) -> str | None:
    """Try the login, returning an error key or None if it worked."""
    try:
        api = await NeeVoApiInterface.login(
            email, password, session=async_get_clientsession(hass)
        )
        tanks = await api.get_tanks_info()
    except InvalidCredentialsError:
        return "invalid_auth"
    except PyNeeVoError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error while checking Nee-Vo login")
        return "unknown"
    return None if tanks else "no_tanks"


class NeeVoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle signing in to a Nee-Vo account."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the email and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            error = await _async_validate(self.hass, email, password)
            if error is None:
                return self.async_create_entry(
                    title=email, data={CONF_EMAIL: email, CONF_PASSWORD: password}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start asking for a new password after a rejected login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        email = entry.data[CONF_EMAIL]
        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            error = await _async_validate(self.hass, email, password)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD: password}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={CONF_EMAIL: email},
            errors=errors,
        )
