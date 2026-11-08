"""Tests for slowing down sign-in attempts after a failed setup."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD
from homeassistant.util import dt as dt_util

from custom_components.neevo_tank import backoff
from custom_components.neevo_tank.const import (
    SETUP_RETRY_FIRST_WAIT,
    SETUP_RETRY_LONGEST_WAIT,
)
from custom_components.neevo_tank.pyneevo.errors import (
    GenericHTTPError,
    InvalidCredentialsError,
)

from .conftest import LOGIN

SERVER_ERROR = GenericHTTPError("HTTP error: 502", status=502)


async def retry(hass, entry) -> None:
    """Make Home Assistant attempt the setup again."""
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_retries_do_not_contact_nee_vo_during_the_wait(
    hass, mock_api, entry, freezer
) -> None:
    entry.add_to_hass(hass)
    failing = AsyncMock(side_effect=SERVER_ERROR)
    with patch(LOGIN, failing):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert failing.call_count == 1

        for _ in range(5):
            freezer.tick(timedelta(seconds=80))
            await retry(hass, entry)
        assert failing.call_count == 1
        assert entry.state is ConfigEntryState.SETUP_RETRY

    await hass.config_entries.async_unload(entry.entry_id)


async def test_tries_again_after_the_wait(hass, mock_api, entry, freezer) -> None:
    entry.add_to_hass(hass)
    failing = AsyncMock(side_effect=SERVER_ERROR)
    with patch(LOGIN, failing):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        freezer.tick(SETUP_RETRY_FIRST_WAIT + timedelta(seconds=1))
        await retry(hass, entry)
        assert failing.call_count == 2
    await hass.config_entries.async_unload(entry.entry_id)


async def test_wait_doubles_up_to_the_longest(hass, freezer) -> None:
    waits = []
    for _ in range(7):
        backoff.record_failure(hass, "entry")
        state = hass.data["neevo_tank"]["entry"]
        waits.append(state.next_attempt - dt_util.utcnow())
    assert waits[:5] == [SETUP_RETRY_FIRST_WAIT * 2**n for n in range(5)]
    assert waits[4] == SETUP_RETRY_LONGEST_WAIT
    assert waits[5] == waits[6] == SETUP_RETRY_LONGEST_WAIT


async def test_success_clears_the_wait(hass, mock_api, entry, freezer) -> None:
    entry.add_to_hass(hass)
    with patch(LOGIN, AsyncMock(side_effect=SERVER_ERROR)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert backoff.should_wait(hass, entry.entry_id)

    freezer.tick(SETUP_RETRY_FIRST_WAIT + timedelta(seconds=1))
    await retry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id not in hass.data["neevo_tank"]


async def test_first_update_failure_also_waits(hass, mock_api, entry) -> None:
    mock_api.refresh_tanks.side_effect = SERVER_ERROR
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert backoff.should_wait(hass, entry.entry_id)

    mock_api.login.reset_mock()
    await retry(hass, entry)
    assert mock_api.login.call_count == 0


async def test_rejected_password_does_not_wait(hass, mock_api, entry) -> None:
    """A clear rejection stops retrying and asks for a new password instead."""
    entry.add_to_hass(hass)
    with patch(LOGIN, AsyncMock(side_effect=InvalidCredentialsError("no"))):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))
    assert not backoff.should_wait(hass, entry.entry_id)


async def test_new_password_clears_the_wait(hass, mock_api, entry) -> None:
    entry.add_to_hass(hass)
    with patch(LOGIN, AsyncMock(side_effect=SERVER_ERROR)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert backoff.should_wait(hass, entry.entry_id)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED


async def test_accounts_wait_separately(hass, freezer) -> None:
    backoff.record_failure(hass, "first")
    assert backoff.should_wait(hass, "first")
    assert not backoff.should_wait(hass, "second")


async def test_removing_the_account_clears_the_wait(hass, mock_api, entry) -> None:
    entry.add_to_hass(hass)
    with patch(LOGIN, AsyncMock(side_effect=SERVER_ERROR)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data["neevo_tank"]
