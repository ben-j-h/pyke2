# pyke2

Async Python client for **KE2 Therm** refrigeration controllers (KE2 Temp, KE2 Low Temp,
KE2 Adaptive, …) through the **KE2 LDA** (Local Device Adapter), the small network
box that bridges a controller's RS-485 Modbus bus to a local JSON API. Local only: no
cloud, no KE2 account.

It powers the [`ha-ke2`](https://github.com/ben-j-h/ha-ke2) Home Assistant integration.

> The reverse-engineering notes (endpoint reference, data model, live test results) are
> in [`research/`](research/). Start with [`research/README.md`](research/README.md).

## Install

```bash
pip install pyke2
```

## Usage

```python
import asyncio
from pyke2 import KE2LDA

async def main():
    async with KE2LDA("192.168.1.50") as lda:          # address the LDA by IP
        for ctrl in (await lda.get_all()).values():
            print(ctrl.key, ctrl.model, ctrl.room_temperature, ctrl.setpoint,
                  ctrl.relay_on, ctrl.mode, ctrl.alarms)

        schema = await lda.get_schema("COM1", 1)        # self-describing field limits
        print(schema.require("Setpoints", "AirTempDiff").bounds())

        await lda.set_setpoints(1, {"RoomTemperature": 55})   # validated, logs in for you

asyncio.run(main())
```

Pass your own `aiohttp.ClientSession` with `session=` (Home Assistant does). Credentials
default to the factory `ke2admin` / `ke2admin`. Reads need none.

### CLI

```bash
python -m pyke2 192.168.1.50 status
python -m pyke2 192.168.1.50 limits
python -m pyke2 192.168.1.50 set RoomTemperature 55
python -m pyke2 192.168.1.50 info
```

## Things worth knowing

* **Use the LDA's IP, not its hostname.** Its web server redirects any other `Host` to
  KE2's cloud. The client resolves a hostname and always sends `Host: <ip>`.
* **Never cable the LDA's LAN port into your network.** It runs a DHCP server. Use the WAN
  port or Wi-Fi.
* Every field's type, range, unit and special values (`999.9` = shorted probe,
  `24:00` = disabled, …) come from the controller's `limits` schema, and writes are
  checked against it before they're sent.
* The LDA can drop off the network now and then. Expect `KE2ConnectionError` and retry
  on your next poll.

## Development

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync                      # creates .venv with the dev group
uv run pytest
uv run ruff check pyke2 tests && uv run ruff format --check pyke2 tests
uv run python -m pyke2 <ip> status
```

Tests run against responses captured from a real KE2 Temp (`research/samples/`).

Not affiliated with KE2 Therm Solutions.
