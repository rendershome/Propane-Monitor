# PyNeeVo

An unofficial asynchronous Python library for interacting with the Nee-Vo tank monitoring platform API.

PyNeeVo allows Python applications to authenticate with Nee-Vo and retrieve propane tank information and readings from connected devices.

## Features

* Asynchronous API built with `aiohttp`
* Username and password authentication
* Retrieve all available tank information
* Refresh tank data from the Nee-Vo platform
* Specific errors for bad credentials, connection problems, timeouts and unexpected responses
* Optional shared `aiohttp` session and configurable timeout

## Installation

```bash
pip install pyneevo
```

## Quick Start

```python
import asyncio

from pyneevo import NeeVoApiInterface
from pyneevo.errors import InvalidCredentialsError, PyNeeVoError

email = "user@example.com"
password = "your-password"

async def main():
    try:
        api = await NeeVoApiInterface.login(email, password)
        tanks = await api.get_tanks_info()
    except InvalidCredentialsError:
        print("Invalid credentials")
        return
    except PyNeeVoError as err:
        print(f"Failed to retrieve tank information: {err}")
        return

    for tank in tanks.values():
        print(
            f"ID: {tank.id} "
            f"Name: {tank.name} "
            f"Level: {tank.level}% "
            f"Last reading: {tank.last_reading}"
        )

if __name__ == "__main__":
    asyncio.run(main())
```

## Refreshing Tank Data

Refreshing individual devices is not yet implemented. As a result, refreshing data updates all devices associated with the account.

`refresh_tanks()` downloads the list again from the Nee-Vo servers. It does not ask the monitor to take a new reading, so a tank's values only change after the monitor has reported in.

```python
await api.refresh_tanks()

tanks = await api.get_tanks_info()

for tank in tanks.values():
    print(
        f"ID: {tank.id} "
        f"Name: {tank.name} "
        f"Level: {tank.level}%"
    )
```

## Available Methods

### Authentication

```python
api = await NeeVoApiInterface.login(email, password)
```

Checks the credentials with the Nee-Vo platform and returns an API interface instance.

Two optional arguments are available:

```python
api = await NeeVoApiInterface.login(
    email,
    password,
    session=my_aiohttp_session,  # Shared session. You stay responsible for closing it.
    timeout=30,  # Limit in seconds for each request. The default is 30.
)
```

### Get Tank Information

```python
tanks = await api.get_tanks_info()
```

Returns a dictionary of all tanks associated with the account, keyed by tank ID. Tanks are downloaded on the first call and the same data is returned afterwards until `refresh_tanks()` is called.

### Refresh Tank Data

```python
await api.refresh_tanks()
```

Downloads the current tank list and replaces the data held by the library. New tanks are added and removed tanks are dropped. If the request fails, the existing data is kept.

### Get Level History

```python
readings = await api.get_level_history(tank.id)

for reading in readings:
    print(reading.date, reading.level, reading.consumption)
```

Returns the tank's recorded history, oldest first. Each entry has a UTC `date`, a `level` in percent and a `consumption` value, and either of the last two can be `None`.

The API does not document `consumption`. In testing with one tank it matched the level drop multiplied by the tank's capacity, which suggests liters, but most days had no value. To measure total usage, calculate it from `level` instead.

The Nee-Vo API chooses the date range. Dates with nothing recorded are left out, so there can be gaps between readings.

### Other Read Operations

These return the API's records as dictionaries.

```python
details = await api.get_tank_details(tank.id)
dealer = await api.get_dealer_details(tank.dealer_id)
campaigns = await api.get_company_campaigns(tank.company_id)
image = await api.get_image(tank.theme_info["ImageId"])

# These contain personal details. Do not log or share them.
user = await api.get_user()
authorizations = await api.get_tank_authorizations(tank.id)
```

`api.must_change_password` holds the value returned at login, or `None` if the API did not send one.

PyNeeVo only reads. It has no methods for operations that change an account, a tank or a fill request, and it does not call them.

### Tank Properties

`id`, `name`, `product`, `level`, `serial_number`, `tank_capacity`, `tank_last_pressure`, `tank_last_pressure_unit`, `last_reading` (a UTC `datetime`) and `data` (the raw record).

Supplier: `company_id`, `dealer_id`, `company_image_id`, `company_name`, `company_support_phone_number`, `fill_request_available`.

Alerts: `notify_at_1`, `notify_at_2`, `notify_critical_levels`, `notify_dispatch`, `notify_dispatch_enabled`, `notify_fill_detection`.

Other: `is_owner`, `consumption_graph_enabled`, `sensor_min_level`, `sensor_max_level`, `tank_form_type`, `tank_primary_value_type`, `theme_info`, and `latitude` and `longitude`, which are private because they show where the tank is.

Every property except `id` and `data` returns `None` if the API did not send that field.

## Error Handling

Every error raised by PyNeeVo is a `PyNeeVoError`.

```python
from pyneevo.errors import (
    GenericHTTPError,
    InvalidCredentialsError,
    InvalidResponseFormat,
    NeeVoConnectionError,
    NeeVoTimeoutError,
    PyNeeVoError,
)

try:
    tanks = await api.get_tanks_info()
except InvalidCredentialsError:
    print("Invalid credentials")
except InvalidResponseFormat:
    print("Unexpected response from Nee-Vo")
except NeeVoTimeoutError:
    print("Nee-Vo did not answer in time")
except NeeVoConnectionError:
    print("Could not reach Nee-Vo")
except GenericHTTPError as err:
    print(f"HTTP error communicating with Nee-Vo: {err.status}")
```

`NeeVoTimeoutError` is a kind of `NeeVoConnectionError`, so catch it first if you handle them differently.

## Current API Coverage

PyNeeVo currently implements read operations only.

Additional endpoints may be added in future releases.

If there is a endpoint you need please create an issue. Pull Requests are also welcome.

## Intended Audience

PyNeeVo is intended for Python developers who want to integrate Nee-Vo tank data into:

* Home automation platforms
* Monitoring dashboards
* Notification systems
* Reporting tools
* Custom integrations

## Development

The tests use only the standard library plus `aiohttp`, and never touch the network:

```bash
pip install -e .
python -m unittest discover -s tests -t .
```

## License

This project is licensed under the MIT License.
