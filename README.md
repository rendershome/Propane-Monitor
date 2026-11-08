# Propane Monitor

An unofficial Home Assistant integration for Nee-Vo propane tank monitors, and the asynchronous Python library behind it.

Built on [PyNeeVo](https://github.com/davidflypei/pyneevo) by [davidflypei](https://github.com/davidflypei). See [Credits](#credits).

This project is not affiliated with or supported by Otodata. It uses an undocumented service that can change without notice. Your use of that service is subject to your Nee-Vo End User License Agreement, so check that it allows how you use this.

## Home Assistant Integration

The **Nee-Vo Tank Monitor** integration adds each tank on your account as a device. It only reads data, and it checks for updates every 6 hours.

### Installing

Requires Home Assistant 2026.10 or newer.

With [HACS](https://hacs.xyz):

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/rendershome/Propane-Monitor` with the type **Integration**.
3. Find **Nee-Vo Tank Monitor** in HACS and download it.
4. Restart Home Assistant.

Or manually, copy `custom_components/neevo_tank` into your Home Assistant `config/custom_components` folder and restart.

Then go to **Settings > Devices & Services > Add Integration**, search for **Nee-Vo Tank Monitor**, and enter the email and password you use in the Nee-Vo app. Home Assistant stores them in its configuration, as it does for other integrations.

### Entities

| Entity | Unit | Notes |
|---|---|---|
| Tank level | % | From today's history when available, which has decimals |
| Propane remaining | L | Level × capacity; Home Assistant can show it in gallons |
| Propane consumed | L | Running total for the Energy dashboard; starts at 0 when installed |
| Consumption rate | L/d | Average over the last 30 days; needs a week of history |
| Estimated days remaining | days | Assumes recent usage continues, so treat it as a rough guide |
| Last reading | | When the monitor last reported |
| Last refill | | Latest refill found in the history |
| Tank capacity | L | Diagnostic |
| Pressure | | Diagnostic; only if the monitor reports it |
| Reading overdue | | Diagnostic; on when the last reading is over 48 hours old |

### Good to Know

- **Consumption is an estimate.** It comes from level changes, ignoring falls under 0.5% until they add up and treating a rise of 5% or more as a refill. Refill detection has not yet been confirmed against a real refill.
- **Energy dashboard:** add **Propane consumed** as a gas source. It is measured in liters of liquid propane, so divide a price per gallon by 3.785.
- **Outages:** sensors keep their last values for up to 24 hours. After that they become unavailable and a repair notice appears. Use **Last reading** or **Reading overdue** to spot a monitor that has stopped reporting.
- **Not a safety device.** Don't rely on this to prevent running out of propane, or in place of normal inspections.
- **Diagnostics** remove your email, password, serial number, tank name, location and supplier, but check them before sharing.

### Removing

Delete the integration under **Settings > Devices & Services**, then remove it from HACS or delete the `custom_components/neevo_tank` folder, and restart. This also deletes its saved consumption total.

## Python Library

The `pyneevo` library in this repository only reads data. It has no methods for operations that change an account, a tank or a fill request.

### Installing the Library

This version differs from the `pyneevo` package on PyPI, so install it from this repository:

```bash
pip install git+https://github.com/rendershome/Propane-Monitor
```

### Quick Start

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

### Signing In

```python
api = await NeeVoApiInterface.login(email, password)
```

Two optional arguments are available:

```python
api = await NeeVoApiInterface.login(
    email,
    password,
    session=my_aiohttp_session,  # Shared session. You stay responsible for closing it.
    timeout=30,  # Limit in seconds for each request. The default is 30.
)
```

`api.must_change_password` holds the value returned at login, or `None` if the API did not send one.

### Tanks

```python
tanks = await api.get_tanks_info()
```

Returns a dictionary of the account's tanks, keyed by tank ID. Tanks are downloaded on the first call, and the same data is returned until you refresh it:

```python
await api.refresh_tanks()
```

This downloads the current list from the Nee-Vo servers, adding new tanks and dropping removed ones. If the request fails, the existing data is kept. It does not ask the monitor for a new reading, so values only change after the monitor has reported in.

### Tank Properties

Every property except `id` and `data` returns `None` if the API did not send that field.

- **Tank:** `id`, `name`, `product`, `level`, `serial_number`, `tank_capacity`, `tank_last_pressure`, `tank_last_pressure_unit`, `last_reading` (a UTC `datetime`) and `data` (the raw record).
- **Supplier:** `company_id`, `dealer_id`, `company_image_id`, `company_name`, `company_support_phone_number`, `fill_request_available`.
- **Alerts:** `notify_at_1`, `notify_at_2`, `notify_critical_levels`, `notify_dispatch`, `notify_dispatch_enabled`, `notify_fill_detection`.
- **Other:** `is_owner`, `consumption_graph_enabled`, `sensor_min_level`, `sensor_max_level`, `tank_form_type`, `tank_primary_value_type`, `theme_info`, and `latitude` and `longitude`, which are private because they show where the tank is.

### Level History

```python
readings = await api.get_level_history(tank.id)

for reading in readings:
    print(reading.date, reading.level, reading.consumption)
```

Returns the tank's recorded history, oldest first. Each entry has a UTC `date`, a `level` in percent and a `consumption` value, and either of the last two can be `None`.

The API chooses the date range. Dates with nothing recorded are left out, so there can be gaps between readings. `consumption` is often empty and its meaning is undocumented, so calculate total usage from `level` instead.

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

### Error Handling

Every error raised by the library is a `PyNeeVoError`.

```python
from pyneevo.errors import (
    GenericHTTPError,
    InvalidCredentialsError,
    InvalidResponseFormat,
    NeeVoConnectionError,
    NeeVoTimeoutError,
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

## Development

The tests never touch the network. They need Linux, because Home Assistant doesn't run natively on Windows:

```bash
pip install pytest-homeassistant-custom-component
python -m pytest tests_ha tests
```

HACS only installs the integration folder, so `src/pyneevo` is copied to `custom_components/neevo_tank/pyneevo`. Copy it again after any library change. A test fails if the two differ.

## Credits

The library is based on [PyNeeVo](https://github.com/davidflypei/pyneevo) by [davidflypei](https://github.com/davidflypei). This version has been changed, so please report problems with it here rather than to that project. The original author has not reviewed or endorsed this project.

## License

MIT. The original PyNeeVo copyright and license are in [LICENSE](LICENSE), with a copy alongside the bundled library in `custom_components/neevo_tank/pyneevo/LICENSE`.
