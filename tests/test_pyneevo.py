"""Tests for pyneevo. All data is synthetic and nothing touches the network."""

import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from aiohttp.client_exceptions import ClientError

from pyneevo import NeeVoApiInterface
from pyneevo.api import HEADERS
from pyneevo.errors import (
    GenericHTTPError,
    InvalidCredentialsError,
    InvalidResponseFormat,
    NeeVoConnectionError,
    NeeVoTimeoutError,
    PyNeeVoError,
)
from pyneevo.tank import Tank

EMAIL = "tester@example.com"
PASSWORD = "not-a-real-password"


def device(tank_id="tank-1", **fields):
    """Build a synthetic device record."""
    record = {"Id": tank_id, "CustomName": "Test Tank", "Level": 62}
    record.update(fields)
    return record


class FakeResponse:
    """Stand in for an aiohttp response."""

    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload

    async def json(self, content_type="application/json"):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeRequest:
    """Stand in for the context manager returned by ``session.get``."""

    def __init__(self, result):
        self.result = result

    async def __aenter__(self):
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """Stand in for an aiohttp session that plays back queued results."""

    def __init__(self, *results):
        self.results = list(results)
        self.requests = []
        self.closed = False

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakeRequest(self.results.pop(0))

    async def close(self):
        self.closed = True


def client(*results):
    """Return a client using a fake session, plus that session."""
    session = FakeSession(*results)
    return NeeVoApiInterface(EMAIL, PASSWORD, session=session), session


class ErrorTests(unittest.IsolatedAsyncioTestCase):
    """Every failure surfaces as a specific library error."""

    async def test_login_success(self):
        session = FakeSession(FakeResponse(200))
        api = await NeeVoApiInterface.login(EMAIL, PASSWORD, session=session)
        self.assertIsInstance(api, NeeVoApiInterface)
        self.assertTrue(session.requests[0][0].endswith(".svc/Login"))

    async def test_credentials_sent_as_basic_auth_header(self):
        session = FakeSession(FakeResponse(200))
        await NeeVoApiInterface.login("a@example.com", "pw", session=session)
        kwargs = session.requests[0][1]
        # base64 of "a@example.com:pw"
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Basic YUBleGFtcGxlLmNvbTpwdw=="
        )
        self.assertNotIn("auth", kwargs)

    async def test_shared_headers_do_not_keep_credentials(self):
        session = FakeSession(FakeResponse(200))
        await NeeVoApiInterface.login(EMAIL, PASSWORD, session=session)
        self.assertNotIn("Authorization", HEADERS)

    async def test_login_401_is_invalid_credentials(self):
        with self.assertRaises(InvalidCredentialsError):
            await NeeVoApiInterface.login(
                EMAIL, PASSWORD, session=FakeSession(FakeResponse(401))
            )

    async def test_fetch_401_is_invalid_credentials(self):
        api, _ = client(FakeResponse(401))
        with self.assertRaises(InvalidCredentialsError):
            await api.get_tanks_info()

    async def test_refresh_401_is_invalid_credentials(self):
        api, _ = client(FakeResponse(401))
        with self.assertRaises(InvalidCredentialsError):
            await api.refresh_tanks()

    async def test_http_error_carries_status(self):
        for call in ("get_tanks_info", "refresh_tanks", "_authenticate"):
            with self.subTest(call=call):
                api, _ = client(FakeResponse(502))
                with self.assertRaises(GenericHTTPError) as caught:
                    await getattr(api, call)()
                self.assertEqual(caught.exception.status, 502)
                self.assertIn("502", str(caught.exception))

    def test_http_error_message_only_still_works(self):
        err = GenericHTTPError("503")
        self.assertEqual(str(err), "503")
        self.assertIsNone(err.status)

    async def test_network_error_is_wrapped_and_compatible(self):
        api, _ = client(ClientError("connection reset"))
        with self.assertRaises(NeeVoConnectionError) as caught:
            await api.get_tanks_info()
        self.assertIsInstance(caught.exception, PyNeeVoError)
        self.assertIsInstance(caught.exception, ClientError)
        self.assertIsInstance(caught.exception.__cause__, ClientError)

    async def test_timeout_is_wrapped_and_compatible(self):
        api, _ = client(asyncio.TimeoutError())
        with self.assertRaises(NeeVoTimeoutError) as caught:
            await api.get_tanks_info()
        self.assertIsInstance(caught.exception, PyNeeVoError)
        self.assertIsInstance(caught.exception, NeeVoConnectionError)
        self.assertIsInstance(caught.exception, TimeoutError)

    async def test_invalid_json_is_invalid_format(self):
        bad_json = json.JSONDecodeError("bad", "<html>", 0)
        api, _ = client(FakeResponse(200, bad_json))
        with self.assertRaises(InvalidResponseFormat):
            await api.get_tanks_info()

    async def test_unexpected_shapes_are_invalid_format(self):
        for payload in (
            {"Message": "Error"},
            "oops",
            None,
            ["not-a-record"],
            [{"CustomName": "no id"}],
            [{"Id": None}],
        ):
            with self.subTest(payload=payload):
                api, _ = client(FakeResponse(200, payload))
                with self.assertRaises(InvalidResponseFormat):
                    await api.get_tanks_info()

    async def test_credentials_absent_from_error_text(self):
        api, _ = client(ClientError("connection reset"))
        with self.assertRaises(NeeVoConnectionError) as caught:
            await api.get_tanks_info()
        self.assertNotIn(PASSWORD, str(caught.exception))


class SessionTests(unittest.IsolatedAsyncioTestCase):
    """Sessions are shared when supplied and cleaned up when owned."""

    async def test_supplied_session_is_left_open(self):
        api, session = client(FakeResponse(200, [device()]))
        await api.refresh_tanks()
        self.assertFalse(session.closed)

    async def test_own_session_is_closed_on_success(self):
        session = FakeSession(FakeResponse(200, [device()]))
        with patch("pyneevo.api.ClientSession", return_value=session):
            await NeeVoApiInterface(EMAIL, PASSWORD).refresh_tanks()
        self.assertTrue(session.closed)

    async def test_own_session_is_closed_on_failure(self):
        session = FakeSession(FakeResponse(500))
        with patch("pyneevo.api.ClientSession", return_value=session):
            with self.assertRaises(GenericHTTPError):
                await NeeVoApiInterface(EMAIL, PASSWORD).refresh_tanks()
        self.assertTrue(session.closed)

    async def test_timeout_setting_reaches_the_request(self):
        session = FakeSession(FakeResponse(200))
        await NeeVoApiInterface.login(EMAIL, PASSWORD, session=session, timeout=5)
        self.assertEqual(session.requests[0][1]["timeout"].total, 5)


class TankListTests(unittest.IsolatedAsyncioTestCase):
    """The held tank list stays in step with the server."""

    async def test_returns_mapping_keyed_by_id(self):
        api, _ = client(FakeResponse(200, [device("a"), device("b")]))
        tanks = await api.get_tanks_info()
        self.assertEqual(set(tanks), {"a", "b"})
        self.assertEqual(tanks["a"].level, 62)

    async def test_get_uses_held_tanks(self):
        api, session = client(FakeResponse(200, [device()]))
        await api.get_tanks_info()
        await api.get_tanks_info()
        self.assertEqual(len(session.requests), 1)

    async def test_refresh_then_get_sends_one_request(self):
        api, session = client(FakeResponse(200, [device()]))
        await api.refresh_tanks()
        tanks = await api.get_tanks_info()
        self.assertEqual(len(session.requests), 1)
        self.assertIn("tank-1", tanks)

    async def test_refresh_adds_new_tanks(self):
        api, _ = client(
            FakeResponse(200, [device("a")]),
            FakeResponse(200, [device("a"), device("b")]),
        )
        await api.refresh_tanks()
        await api.refresh_tanks()
        self.assertEqual(set(await api.get_tanks_info()), {"a", "b"})

    async def test_refresh_drops_removed_tanks(self):
        api, _ = client(
            FakeResponse(200, [device("a"), device("b")]),
            FakeResponse(200, [device("b")]),
        )
        await api.refresh_tanks()
        await api.refresh_tanks()
        self.assertEqual(set(await api.get_tanks_info()), {"b"})

    async def test_refresh_clears_a_dropped_field(self):
        api, _ = client(
            FakeResponse(200, [device(Level=62)]),
            FakeResponse(200, [{"Id": "tank-1", "CustomName": "Test Tank"}]),
        )
        await api.refresh_tanks()
        await api.refresh_tanks()
        tanks = await api.get_tanks_info()
        self.assertIsNone(tanks["tank-1"].level)
        self.assertNotIn("Level", tanks["tank-1"].data)

    async def test_refresh_keeps_object_and_calls_callback(self):
        api, _ = client(
            FakeResponse(200, [device(Level=62)]),
            FakeResponse(200, [device(Level=50)]),
        )
        await api.refresh_tanks()
        tank = (await api.get_tanks_info())["tank-1"]
        calls = []
        tank.set_update_callback(lambda: calls.append(tank.level))
        await api.refresh_tanks()
        self.assertIs((await api.get_tanks_info())["tank-1"], tank)
        self.assertEqual(calls, [50])

    async def test_failed_refresh_keeps_held_tanks(self):
        api, _ = client(FakeResponse(200, [device()]), FakeResponse(502))
        await api.refresh_tanks()
        with self.assertRaises(GenericHTTPError):
            await api.refresh_tanks()
        self.assertEqual((await api.get_tanks_info())["tank-1"].level, 62)


class LevelHistoryTests(unittest.IsolatedAsyncioTestCase):
    """Level history is parsed, filtered and validated."""

    AUG_1 = "/Date(1785542400000)/"
    AUG_2 = "/Date(1785628800000)/"
    AUG_3 = "/Date(1785715200000)/"

    def history(self, *points):
        return FakeResponse(200, {"CurrentLevel": 49, "GraphLevelsData": list(points)})

    async def test_parses_readings(self):
        api, session = client(
            self.history({"Date": self.AUG_1, "Level": 53.6, "Consumption": None})
        )
        readings = await api.get_level_history("tank-1")
        self.assertEqual(len(readings), 1)
        self.assertEqual(
            readings[0].date, datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(readings[0].level, 53.6)
        self.assertIsNone(readings[0].consumption)
        self.assertTrue(session.requests[0][0].endswith("/GetPropaneLevels/tank-1"))

    async def test_tank_id_is_escaped(self):
        api, session = client(self.history())
        await api.get_level_history("a/b c")
        self.assertTrue(session.requests[0][0].endswith("/GetPropaneLevels/a%2Fb%20c"))

    async def test_integer_id_is_accepted(self):
        api, session = client(self.history())
        await api.get_level_history(12345)
        self.assertTrue(session.requests[0][0].endswith("/GetPropaneLevels/12345"))

    async def test_empty_dates_are_left_out(self):
        api, _ = client(
            self.history(
                {"Date": self.AUG_1, "Level": 53.6, "Consumption": None},
                {"Date": self.AUG_2, "Level": None, "Consumption": None},
            )
        )
        readings = await api.get_level_history("tank-1")
        self.assertEqual([reading.level for reading in readings], [53.6])

    async def test_zero_level_is_kept(self):
        api, _ = client(self.history({"Date": self.AUG_1, "Level": 0}))
        readings = await api.get_level_history("tank-1")
        self.assertEqual(readings[0].level, 0.0)

    async def test_consumption_only_entry_is_kept(self):
        api, _ = client(
            self.history({"Date": self.AUG_1, "Level": None, "Consumption": 2.5})
        )
        readings = await api.get_level_history("tank-1")
        self.assertIsNone(readings[0].level)
        self.assertEqual(readings[0].consumption, 2.5)

    async def test_non_numeric_values_are_ignored(self):
        api, _ = client(
            self.history(
                {"Date": self.AUG_1, "Level": "n/a", "Consumption": True},
                {"Date": self.AUG_2, "Level": 50, "Consumption": "n/a"},
            )
        )
        readings = await api.get_level_history("tank-1")
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].level, 50.0)
        self.assertIsNone(readings[0].consumption)

    async def test_sorted_oldest_first(self):
        api, _ = client(
            self.history(
                {"Date": self.AUG_3, "Level": 51},
                {"Date": self.AUG_1, "Level": 53},
                {"Date": self.AUG_2, "Level": 52},
            )
        )
        readings = await api.get_level_history("tank-1")
        self.assertEqual([reading.level for reading in readings], [53.0, 52.0, 51.0])

    async def test_empty_history_is_empty_list(self):
        api, _ = client(self.history())
        self.assertEqual(await api.get_level_history("tank-1"), [])

    async def test_unexpected_shapes_are_invalid_format(self):
        for payload in (
            None,
            [],
            "oops",
            {},
            {"GraphLevelsData": None},
            {"GraphLevelsData": ["not-a-record"]},
            {"GraphLevelsData": [{"Level": 50}]},
            {"GraphLevelsData": [{"Date": "yesterday", "Level": 50}]},
        ):
            with self.subTest(payload=payload):
                api, _ = client(FakeResponse(200, payload))
                with self.assertRaises(InvalidResponseFormat):
                    await api.get_level_history("tank-1")

    async def test_errors_match_the_other_calls(self):
        api, _ = client(FakeResponse(401))
        with self.assertRaises(InvalidCredentialsError):
            await api.get_level_history("tank-1")
        api, _ = client(FakeResponse(502))
        with self.assertRaises(GenericHTTPError):
            await api.get_level_history("tank-1")


class ReadOperationTests(unittest.IsolatedAsyncioTestCase):
    """The added read operations request the right path and validate responses."""

    RECORD_CALLS = (
        ("get_tank_details", "GetPropaneDeviceDetails/x"),
        ("get_dealer_details", "GetDealerDetails/x"),
    )
    LIST_CALLS = (
        ("get_company_campaigns", "GetCompanyCampaigns/x"),
        ("get_tank_authorizations", "GetPropaneDeviceAuthorizations/x"),
    )

    async def test_records(self):
        for method, path in self.RECORD_CALLS:
            with self.subTest(method=method):
                api, session = client(FakeResponse(200, {"Name": "n"}))
                self.assertEqual(await getattr(api, method)("x"), {"Name": "n"})
                self.assertTrue(session.requests[0][0].endswith(f".svc/{path}"))

    async def test_lists(self):
        for method, path in self.LIST_CALLS:
            with self.subTest(method=method):
                api, session = client(FakeResponse(200, [{"Name": "n"}]))
                self.assertEqual(await getattr(api, method)("x"), [{"Name": "n"}])
                self.assertTrue(session.requests[0][0].endswith(f".svc/{path}"))

    async def test_get_user(self):
        api, session = client(FakeResponse(200, {"FirstName": "Test"}))
        self.assertEqual(await api.get_user(), {"FirstName": "Test"})
        self.assertTrue(session.requests[0][0].endswith(".svc/User"))

    async def test_get_image(self):
        api, session = client(FakeResponse(200, {"Image": "abc"}))
        self.assertEqual(await api.get_image("x"), "abc")
        self.assertTrue(session.requests[0][0].endswith(".svc/GetImage/x"))

    async def test_get_image_without_image(self):
        api, _ = client(FakeResponse(200, {}))
        self.assertIsNone(await api.get_image("x"))

    async def test_ids_are_escaped(self):
        api, session = client(FakeResponse(200, {}))
        await api.get_dealer_details("a/../DeleteUser")
        self.assertTrue(
            session.requests[0][0].endswith("/GetDealerDetails/a%2F..%2FDeleteUser")
        )

    async def test_wrong_shapes_are_invalid_format(self):
        for method, _ in self.RECORD_CALLS:
            for payload in ([], "oops", None):
                with self.subTest(method=method, payload=payload):
                    api, _session = client(FakeResponse(200, payload))
                    with self.assertRaises(InvalidResponseFormat):
                        await getattr(api, method)("x")
        for method, _ in self.LIST_CALLS:
            for payload in ({}, "oops", None, ["not-a-record"]):
                with self.subTest(method=method, payload=payload):
                    api, _session = client(FakeResponse(200, payload))
                    with self.assertRaises(InvalidResponseFormat):
                        await getattr(api, method)("x")

    async def test_errors_match_the_other_calls(self):
        api, _ = client(FakeResponse(401))
        with self.assertRaises(InvalidCredentialsError):
            await api.get_user()
        api, _ = client(FakeResponse(502))
        with self.assertRaises(GenericHTTPError):
            await api.get_dealer_details("x")

    async def test_login_reads_must_change_password(self):
        session = FakeSession(FakeResponse(200, {"MustChangePassword": True}))
        api = await NeeVoApiInterface.login(EMAIL, PASSWORD, session=session)
        self.assertIs(api.must_change_password, True)

    async def test_login_survives_an_unreadable_body(self):
        bad_json = json.JSONDecodeError("bad", "", 0)
        for payload in (bad_json, None, "ok", []):
            with self.subTest(payload=payload):
                session = FakeSession(FakeResponse(200, payload))
                api = await NeeVoApiInterface.login(EMAIL, PASSWORD, session=session)
                self.assertIsNone(api.must_change_password)

    def test_no_change_operations_are_reachable(self):
        """Only read operations are in the library's source."""
        import inspect

        import pyneevo.api

        source = inspect.getsource(pyneevo.api)
        for name in (
            "DeletePropaneDevice",
            "DeleteUser",
            "RevokePropaneDeviceAuthorization",
            "GenerateAccessAutorizationVoucher",
            "GenerateTransfertAutorizationVoucher",
            "UpdateCampaignClickCount",
            "UpdatePropaneDevice",
            "UpdateUser",
            "ChangePassword",
            "SendFillRequest",
            "RegisterPropaneDevice",
        ):
            with self.subTest(name=name):
                # Operation names appear in source as the start of a string.
                self.assertNotIn(f'"{name}', source)


class TankFieldTests(unittest.TestCase):
    """Tank properties tolerate the API's field variations."""

    def test_every_documented_field_has_a_property(self):
        fields = {
            "latitude": "Latitude",
            "longitude": "Longitude",
            "company_id": "CompanyId",
            "dealer_id": "DealerId",
            "company_image_id": "CompanyImageId",
            "company_name": "CompanyName",
            "company_support_phone_number": "CompanySupportPhoneNumber",
            "fill_request_available": "CompanyFillRequestAvailable",
            "notify_at_1": "NotifyAt1",
            "notify_at_2": "NotifyAt2",
            "notify_critical_levels": "NotifyCriticalLevels",
            "notify_dispatch": "NotifyDispatch",
            "notify_dispatch_enabled": "NotifyDispatchEnabled",
            "notify_fill_detection": "NotifyFillDetection",
            "is_owner": "IsOwner",
            "consumption_graph_enabled": "IsConsumptionVolumeGraphEnabled",
            "sensor_min_level": "SensorMinLevel",
            "sensor_max_level": "SensorMaxLevel",
            "tank_form_type": "TankFormType",
            "tank_primary_value_type": "TankPrimaryValueType",
            "theme_info": "ThemeInfo",
        }
        for attribute, field in fields.items():
            with self.subTest(attribute=attribute):
                marker = object()
                self.assertIs(getattr(self.tank(**{field: marker}), attribute), marker)
                self.assertIsNone(getattr(Tank({"Id": "tank-1"}, None), attribute))

    def test_top_level_imports(self):
        from pyneevo import LevelReading, parse_net_date

        self.assertEqual(LevelReading._fields, ("date", "level", "consumption"))
        self.assertIsNone(parse_net_date("nope"))

    def tank(self, **fields):
        return Tank(device(**fields), None)

    def test_level_field_names(self):
        self.assertEqual(self.tank(Level=40).level, 40)
        self.assertEqual(self.tank(CurrentLevel=41).level, 41)
        self.assertEqual(self.tank(Level=40, CurrentLevel=41).level, 41)
        self.assertEqual(self.tank(Level=0).level, 0)

    def test_product_either_case(self):
        self.assertEqual(self.tank(Product="Propane").product, "Propane")
        self.assertEqual(self.tank(product="Propane").product, "Propane")

    def test_missing_optional_fields_are_none(self):
        tank = Tank({"Id": "tank-1"}, None)
        for field in (
            "name",
            "product",
            "level",
            "serial_number",
            "tank_capacity",
            "tank_last_pressure",
            "tank_last_pressure_unit",
            "last_reading",
        ):
            with self.subTest(field=field):
                self.assertIsNone(getattr(tank, field))

    def test_update_for_other_tank_is_ignored(self):
        tank = self.tank()
        calls = []
        tank.set_update_callback(lambda: calls.append(1))
        tank._update_tank_info({"Id": "other", "Level": 1})
        self.assertEqual(tank.level, 62)
        self.assertEqual(calls, [])

    def test_last_reading(self):
        expected = datetime(2026, 6, 9, 18, 0, tzinfo=timezone.utc)
        for text in (
            "/Date(1781028000000-0700)/",
            "/Date(1781028000000+0000)/",
            "/Date(1781028000000)/",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.tank(LastReadingDate=text).last_reading, expected)

    def test_last_reading_rejects_junk(self):
        for value in (
            None,
            "",
            "not a date",
            "/Date(123abc)/",
            12345,
            "/Date(999999999999999999999)/",
        ):
            with self.subTest(value=value):
                self.assertIsNone(self.tank(LastReadingDate=value).last_reading)


if __name__ == "__main__":
    unittest.main()
