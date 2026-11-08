"""Fixtures for the integration tests. All data is synthetic and nothing uses the network."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neevo_tank.const import DOMAIN
from custom_components.neevo_tank.pyneevo import LevelReading, Tank

EMAIL = "tester@example.com"
PASSWORD = "not-a-real-password"
TANK_ID = "tank-1"
LOGIN = "custom_components.neevo_tank.pyneevo.api.NeeVoApiInterface.login"


def net_date(moment: datetime) -> str:
    """Format a time the way the API does."""
    return f"/Date({int(moment.timestamp() * 1000)})/"


def make_tank(tank_id: str = TANK_ID, **fields) -> Tank:
    """Build a real Tank from a synthetic record."""
    record = {
        "Id": tank_id,
        "CustomName": "Test Tank",
        "SerialNumber": 123456,
        "Level": 49,
        "TankCapacity": 1000.0,
        "LastReadingDate": net_date(dt_util.utcnow() - timedelta(hours=2)),
        "TankLastPressure": None,
        "TankPressureDisplayUnitSymbol": "kPa",
        "Latitude": 45.5,
        "Longitude": -73.5,
        "CompanyName": "Test Propane Co",
        "DealerId": "dealer-1",
    }
    record.update(fields)
    return Tank(record, None)


def history(*levels: float) -> list[LevelReading]:
    """Build one reading per day, ending today, oldest first."""
    today = dt_util.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        LevelReading(today - timedelta(days=len(levels) - 1 - index), level, None)
        for index, level in enumerate(levels)
    ]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow custom integrations to load in every test."""
    return


@pytest.fixture
def mock_api():
    """Replace the login with a client returning synthetic data."""
    api = MagicMock()
    api.must_change_password = False
    api.refresh_tanks = AsyncMock()
    api.get_tanks_info = AsyncMock(return_value={TANK_ID: make_tank()})
    api.get_level_history = AsyncMock(return_value=history(50.0, 49.37))
    with patch(LOGIN, AsyncMock(return_value=api)) as login:
        api.login = login
        yield api


@pytest.fixture
def entry() -> MockConfigEntry:
    """Return a config entry for the synthetic account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD},
        unique_id=EMAIL,
    )
