"""Tests for setup, entities, failure handling and diagnostics."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.neevo_tank.const import DOMAIN, UPDATE_INTERVAL
from custom_components.neevo_tank.diagnostics import async_get_config_entry_diagnostics
from custom_components.neevo_tank.pyneevo.errors import (
    GenericHTTPError,
    InvalidCredentialsError,
    NeeVoConnectionError,
)

from .conftest import EMAIL, LOGIN, PASSWORD, TANK_ID, history, make_tank, net_date


def state(hass, key, platform="sensor"):
    """Return an entity's state by its unique ID."""
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{TANK_ID}_{key}"
    )
    assert entity_id, f"no entity for {key}"
    return hass.states.get(entity_id)


async def setup(hass, entry):
    """Set up the integration."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def poll(hass, coordinator):
    """Run one update and let its results settle."""
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_setup_and_unload(hass, mock_api, entry) -> None:
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_sensor_values(hass, mock_api, entry) -> None:
    await setup(hass, entry)
    # The decimal value from today's history beats the tank list's whole number.
    assert state(hass, "level").state == "49.37"
    assert state(hass, "remaining").state == "493.7"
    assert state(hass, "capacity").state == "1000.0"
    assert state(hass, "consumed").state == "0.0"
    assert state(hass, "last_reading").state != STATE_UNKNOWN
    assert state(hass, "last_refill").state == STATE_UNKNOWN
    assert state(hass, "reading_overdue", "binary_sensor").state == STATE_OFF
    # Pressure was empty, so there is no sensor for it.
    assert (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{TANK_ID}_pressure")
        is None
    )


async def test_device(hass, mock_api, entry) -> None:
    await setup(hass, entry)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "Test Tank"
    assert devices[0].serial_number == "123456"


async def test_level_falls_back_without_recent_history(hass, mock_api, entry) -> None:
    mock_api.get_level_history.return_value = []
    await setup(hass, entry)
    assert state(hass, "level").state == "49.0"


async def test_stale_history_is_not_used_for_level(hass, mock_api, entry) -> None:
    mock_api.get_level_history.return_value = history(60.0, 60.0, 60.0, 60.0)[:2]
    await setup(hass, entry)
    assert state(hass, "level").state == "49.0"


async def test_out_of_range_level_is_unknown(hass, mock_api, entry) -> None:
    mock_api.get_tanks_info.return_value = {TANK_ID: make_tank(Level=150)}
    mock_api.get_level_history.return_value = []
    await setup(hass, entry)
    assert state(hass, "level").state == STATE_UNKNOWN
    assert state(hass, "remaining").state == STATE_UNKNOWN


async def test_rate_and_days_remaining(hass, mock_api, entry) -> None:
    # 1% a day of a 1000 L tank is 10 L a day, with 500 L left.
    mock_api.get_level_history.return_value = history(*range(60, 49, -1))
    await setup(hass, entry)
    assert state(hass, "consumption_rate").state == "10.0"
    assert state(hass, "days_remaining").state == "50"


async def test_rate_needs_a_week_of_history(hass, mock_api, entry) -> None:
    mock_api.get_level_history.return_value = history(52.0, 51.0, 50.0)
    await setup(hass, entry)
    assert state(hass, "consumption_rate").state == STATE_UNKNOWN
    assert state(hass, "days_remaining").state == STATE_UNKNOWN


async def test_meter_counts_new_readings_and_survives_reload(
    hass, mock_api, entry
) -> None:
    coordinator = await setup(hass, entry)
    meter = coordinator._meters[TANK_ID]
    meter.last_date -= timedelta(days=1)  # Pretend today's reading is new.
    meter.watermark_pct = 50.0
    mock_api.get_level_history.return_value = history(49.0)
    await poll(hass, coordinator)
    assert state(hass, "consumed").state == "10.0"

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "consumed").state == "10.0"


async def test_overdue_reading(hass, mock_api, entry) -> None:
    old = dt_util.utcnow() - timedelta(hours=49)
    mock_api.get_tanks_info.return_value = {
        TANK_ID: make_tank(LastReadingDate=net_date(old))
    }
    await setup(hass, entry)
    assert state(hass, "reading_overdue", "binary_sensor").state == STATE_ON


async def test_pressure_sensor_when_reported(hass, mock_api, entry) -> None:
    mock_api.get_tanks_info.return_value = {
        TANK_ID: make_tank(TankLastPressure=100.0)
    }
    await setup(hass, entry)
    pressure = state(hass, "pressure")
    assert pressure.state == "100.0"
    assert pressure.attributes["device_class"] == "pressure"


async def test_new_tank_appears_without_reload(hass, mock_api, entry) -> None:
    coordinator = await setup(hass, entry)
    mock_api.get_tanks_info.return_value = {
        TANK_ID: make_tank(),
        "tank-2": make_tank("tank-2", CustomName="Second Tank"),
    }
    await poll(hass, coordinator)
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "tank-2_level")


async def test_removed_tank_goes_unavailable(hass, mock_api, entry) -> None:
    coordinator = await setup(hass, entry)
    mock_api.get_tanks_info.return_value = {"tank-2": make_tank("tank-2")}
    await poll(hass, coordinator)
    assert state(hass, "level").state == STATE_UNAVAILABLE


async def test_setup_rejected_password_starts_reauth(hass, mock_api, entry) -> None:
    entry.add_to_hass(hass)
    with patch(LOGIN, AsyncMock(side_effect=InvalidCredentialsError("no"))):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))


async def test_setup_connection_error_retries(hass, mock_api, entry) -> None:
    entry.add_to_hass(hass)
    with patch(LOGIN, AsyncMock(side_effect=NeeVoConnectionError("down"))):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_first_update_failure_retries(hass, mock_api, entry) -> None:
    mock_api.refresh_tanks.side_effect = GenericHTTPError("x", status=502)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_password_during_poll_starts_reauth(
    hass, mock_api, entry
) -> None:
    coordinator = await setup(hass, entry)
    mock_api.refresh_tanks.side_effect = InvalidCredentialsError("no")
    await poll(hass, coordinator)
    assert any(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))


async def test_rejected_password_during_history_starts_reauth(
    hass, mock_api, entry
) -> None:
    coordinator = await setup(hass, entry)
    mock_api.get_level_history.side_effect = InvalidCredentialsError("no")
    await poll(hass, coordinator)
    assert any(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))


async def test_history_failure_does_not_fail_the_update(hass, mock_api, entry) -> None:
    coordinator = await setup(hass, entry)
    mock_api.get_level_history.side_effect = GenericHTTPError("x", status=500)
    await poll(hass, coordinator)
    assert coordinator.last_update_success
    assert state(hass, "level").state == "49.0"


@pytest.mark.parametrize(
    "error", [GenericHTTPError("x", status=502), NeeVoConnectionError("down")]
)
async def test_short_outage_keeps_last_values(hass, mock_api, entry, error) -> None:
    coordinator = await setup(hass, entry)
    mock_api.refresh_tanks.side_effect = error
    await poll(hass, coordinator)
    assert state(hass, "level").state == "49.37"
    assert coordinator.first_failure is not None
    assert not ir.async_get(hass).issues


async def test_empty_tank_list_is_treated_as_an_outage(hass, mock_api, entry) -> None:
    coordinator = await setup(hass, entry)
    mock_api.get_tanks_info.return_value = {}
    await poll(hass, coordinator)
    assert state(hass, "level").state == "49.37"


async def test_long_outage_goes_unavailable_and_raises_issue(
    hass, mock_api, entry
) -> None:
    coordinator = await setup(hass, entry)
    long_ago = dt_util.utcnow() - timedelta(hours=25)
    coordinator._last_success = long_ago
    coordinator.first_failure = long_ago
    mock_api.refresh_tanks.side_effect = GenericHTTPError("x", status=502)

    await poll(hass, coordinator)
    assert state(hass, "level").state == STATE_UNAVAILABLE
    issue_id = f"cloud_unreachable_{entry.entry_id}"
    assert (DOMAIN, issue_id) in ir.async_get(hass).issues

    mock_api.refresh_tanks.side_effect = None
    await poll(hass, coordinator)
    assert state(hass, "level").state == "49.37"
    assert coordinator.first_failure is None
    assert (DOMAIN, issue_id) not in ir.async_get(hass).issues


async def test_scheduled_polling(hass, mock_api, entry) -> None:
    await setup(hass, entry)
    before = mock_api.refresh_tanks.call_count
    async_fire_time_changed(hass, dt_util.utcnow() + UPDATE_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert mock_api.refresh_tanks.call_count == before + 1


async def test_damaged_storage_is_ignored(hass, mock_api, entry, hass_storage) -> None:
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "data": {TANK_ID: {"total_l": "garbage"}, "other": "garbage"},
    }
    coordinator = await setup(hass, entry)
    assert coordinator.data[TANK_ID].consumed_l == 0.0


async def test_diagnostics_hide_private_details(hass, mock_api, entry) -> None:
    await setup(hass, entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diagnostics)
    for private in (
        EMAIL,
        PASSWORD,
        TANK_ID,
        "Test Tank",
        "123456",
        "45.5",
        "-73.5",
        "Test Propane Co",
        "dealer-1",
    ):
        assert private not in text
    assert diagnostics["tanks"][0]["level_pct"] == 49.37


async def test_remove_entry_cleans_up(hass, mock_api, entry, hass_storage) -> None:
    coordinator = await setup(hass, entry)
    await coordinator.async_save_meters()
    assert f"{DOMAIN}.{entry.entry_id}" in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage
