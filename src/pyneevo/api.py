"""Client for the Nee-Vo API."""

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout
from aiohttp.client_exceptions import ClientError

from .errors import (
    GenericHTTPError,
    InvalidCredentialsError,
    InvalidResponseFormat,
    NeeVoConnectionError,
    NeeVoTimeoutError,
)
from .tank import LevelReading, Tank, parse_net_date

_LOGGER = logging.getLogger(__name__)

ApiType = TypeVar("ApiType", bound="NeeVoApiInterface")


def _number_or_none(value: Any) -> Optional[float]:
    """Return a numeric value as a float, or ``None`` for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


HOST ="ws.otodatanetwork.com"
REST_URL = f"https://{HOST}/neevoapp/v1/DataService.svc/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "pyneevo/1.0.0",
}
DEFAULT_TIMEOUT = 30.0


class NeeVoApiInterface:
    """Talk to the Nee-Vo API for one account."""

    def __init__(
        self,
        email: str,
        password: str,
        session: Optional[ClientSession] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize.

        ``session`` is an optional aiohttp session owned by the caller, who
        stays responsible for closing it. Without one, each request opens and
        closes its own. ``timeout`` is the limit in seconds for each request.
        """
        self.email = email
        self.password = password
        self._session = session
        self._timeout = timeout
        self._tanks: Dict[Any, Tank] = {}
        self.must_change_password: Optional[bool] = None

    @classmethod
    async def login(
        cls: Type[ApiType],
        email: str,
        password: str,
        session: Optional[ClientSession] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> ApiType:
        """Check the credentials and return a ready-to-use client."""
        instance = cls(email, password, session=session, timeout=timeout)
        await instance._authenticate()
        return instance

    async def _request(self, endpoint: str, parse_json: bool = False) -> Any:
        """Send one GET request and translate every failure to a library error."""
        # Built by hand because aiohttp is removing BasicAuth in version 4. Latin-1
        # matches what aiohttp's BasicAuth used by default.
        credentials = f"{self.email}:{self.password}".encode("latin1")
        headers = {
            **HEADERS,
            "Authorization": f"Basic {base64.b64encode(credentials).decode('ascii')}",
        }
        session = self._session if self._session is not None else ClientSession()
        try:
            async with session.get(
                f"{REST_URL}{endpoint}",
                headers=headers,
                timeout=ClientTimeout(total=self._timeout),
            ) as response:
                if response.status == 401:
                    raise InvalidCredentialsError("Invalid credentials")
                if response.status != 200:
                    raise GenericHTTPError(
                        f"HTTP error: {response.status}", status=response.status
                    )
                if not parse_json:
                    return None
                try:
                    return await response.json(content_type=None)
                except ValueError as err:
                    raise InvalidResponseFormat("Response is not valid JSON") from err
        except asyncio.TimeoutError as err:
            raise NeeVoTimeoutError(
                f"No response from Nee-Vo within {self._timeout} seconds"
            ) from err
        except ClientError as err:
            raise NeeVoConnectionError(str(err) or type(err).__name__) from err
        finally:
            if self._session is None:
                await session.close()

    async def _authenticate(self) -> None:
        """Check the credentials against the API."""
        _LOGGER.debug("Authenticating with Nee-Vo API")
        try:
            result = await self._request("Login", parse_json=True)
        except InvalidResponseFormat:
            # The credentials were accepted, so an unreadable body is not a failure.
            result = None
        if isinstance(result, dict):
            self.must_change_password = result.get("MustChangePassword")

    async def _get_record(self, endpoint: str, record_id: Any = None) -> Dict[str, Any]:
        """Fetch one operation that returns a single record."""
        result = await self._request(self._path(endpoint, record_id), parse_json=True)
        if not isinstance(result, dict):
            raise InvalidResponseFormat(f"Expected a record from {endpoint}")
        return result

    async def _get_records(self, endpoint: str, record_id: Any) -> List[Dict[str, Any]]:
        """Fetch one operation that returns a list of records."""
        result = await self._request(self._path(endpoint, record_id), parse_json=True)
        if not isinstance(result, list) or not all(
            isinstance(item, dict) for item in result
        ):
            raise InvalidResponseFormat(f"Expected a list of records from {endpoint}")
        return result

    @staticmethod
    def _path(endpoint: str, record_id: Any = None) -> str:
        """Build a request path, escaping any ID."""
        if record_id is None:
            return endpoint
        return f"{endpoint}/{quote(str(record_id), safe='')}"

    async def get_tank_details(self, tank_id: Any) -> Dict[str, Any]:
        """Return the raw details record for one tank.

        Contains the tank's serial number and alert settings.
        """
        return await self._get_record("GetPropaneDeviceDetails", tank_id)

    async def get_dealer_details(self, dealer_id: Any) -> Dict[str, Any]:
        """Return the raw contact details and opening hours of a propane supplier."""
        return await self._get_record("GetDealerDetails", dealer_id)

    async def get_company_campaigns(self, company_id: Any) -> List[Dict[str, Any]]:
        """Return the raw campaign records of a propane supplier."""
        return await self._get_records("GetCompanyCampaigns", company_id)

    async def get_image(self, image_id: Any) -> Optional[str]:
        """Return an image as the string the API sends, or ``None`` if there is none."""
        record = await self._get_record("GetImage", image_id)
        return record.get("Image")

    async def get_user(self) -> Dict[str, Any]:
        """Return the raw profile of the signed-in account.

        Contains personal details, including name, address and phone number. Do
        not log or share it.
        """
        return await self._get_record("User")

    async def get_tank_authorizations(self, tank_id: Any) -> List[Dict[str, Any]]:
        """Return the raw records of the people with access to a tank.

        Contains people's names and activation codes. Do not log or share them.
        """
        return await self._get_records("GetPropaneDeviceAuthorizations", tank_id)

    async def GetAllDisplayPropaneDevices(self) -> List[Dict[str, Any]]:
        """Return the raw device records for the account."""
        devices = await self._request("GetAllDisplayPropaneDevices", parse_json=True)
        if not isinstance(devices, list):
            raise InvalidResponseFormat("Expected a list of devices")
        for device in devices:
            if not isinstance(device, dict) or device.get("Id") is None:
                raise InvalidResponseFormat("Device record has no Id")
        return devices

    async def get_tanks_info(self) -> Dict[Any, Tank]:
        """Return tanks keyed by ID, fetching them if none are held yet."""
        if not self._tanks:
            await self.refresh_tanks()
        return self._tanks

    async def refresh_tanks(self) -> None:
        """Download the tank list again and replace what is held.

        This re-reads what the Nee-Vo servers already have; it does not ask the
        monitor for a new reading. New tanks are added and removed tanks are
        dropped. A tank that is still listed keeps its ``Tank`` object, so any
        update callback stays attached. On failure the held tanks are unchanged.
        """
        devices = await self.GetAllDisplayPropaneDevices()
        tanks: Dict[Any, Tank] = {}
        for device in devices:
            tank = self._tanks.get(device["Id"])
            if tank is None:
                tank = Tank(device, self)
            else:
                tank._update_tank_info(device)
            tanks[device["Id"]] = tank
        self._tanks = tanks

    async def get_level_history(self, tank_id: Any) -> List[LevelReading]:
        """Return a tank's recorded level history, oldest first.

        The API also lists dates with nothing recorded, including future days.
        Those are left out, so gaps can appear between readings. The API chooses
        the date range.
        """
        payload = await self._request(
            self._path("GetPropaneLevels", tank_id), parse_json=True
        )
        points = payload.get("GraphLevelsData") if isinstance(payload, dict) else None
        if not isinstance(points, list):
            raise InvalidResponseFormat("Expected a list of level readings")

        readings = []
        for point in points:
            date = parse_net_date(point.get("Date")) if isinstance(point, dict) else None
            if date is None:
                raise InvalidResponseFormat("Level reading has no valid date")
            level = _number_or_none(point.get("Level"))
            consumption = _number_or_none(point.get("Consumption"))
            if level is not None or consumption is not None:
                readings.append(LevelReading(date, level, consumption))
        readings.sort(key=lambda reading: reading.date)
        return readings
