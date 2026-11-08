"""Tests for the sign-in screens."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.neevo_tank.const import DOMAIN
from custom_components.neevo_tank.pyneevo.errors import (
    GenericHTTPError,
    InvalidCredentialsError,
    NeeVoConnectionError,
)

from .conftest import EMAIL, LOGIN, PASSWORD

INPUT = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD}


async def test_sign_in(hass, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == INPUT
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (InvalidCredentialsError("no"), "invalid_auth"),
        (GenericHTTPError("HTTP error: 502", status=502), "cannot_connect"),
        (NeeVoConnectionError("down"), "cannot_connect"),
        (RuntimeError("surprise"), "unknown"),
    ],
)
async def test_sign_in_errors(hass, mock_api, error, key) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(LOGIN, AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


async def test_no_tanks(hass, mock_api) -> None:
    mock_api.get_tanks_info.return_value = {}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["errors"] == {"base": "no_tanks"}


async def test_account_added_twice(hass, mock_api, entry) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass, mock_api, entry) -> None:
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with patch(LOGIN, AsyncMock(side_effect=InvalidCredentialsError("no"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "still-wrong"}
        )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    await hass.async_block_till_done()
