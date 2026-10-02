# 04 — Home Assistant architecture

Two public repos:

| Repo | What | Ships as |
|------|------|----------|
| `pyke2` | Async client library for the KE2 LDA API + this research | PyPI `pyke2` |
| `ha-ke2` | HA custom integration (HACS), depends on `pyke2==x.y.z` | HACS custom repository |

## `pyke2` — library

* `aiohttp`-based, takes a caller-supplied `ClientSession` (HA's shared session).
  No sync API.
* `KE2LDA(host, username="ke2admin", password="ke2admin", session=…)`:
  * `async get_all() -> dict[int, Controller]`, one call to `/modbus/<if>/all` for every interface.
  * `async get_limits(addr) -> Schema` (cached; it only changes with firmware).
  * `async set_setpoints(addr, {field: value}) -> None`. Validates against the schema
    (range, discrete, special values, `Time` formats, unit), logs in lazily, re-logs on
    an auth failure once, and raises `KE2WriteError` on a non-`Success` reply.
  * `async set_system_on(addr, on: bool)` (`Manual Control`, only when present) and
    `async next_mode(addr)`.
  * `async get_device_info() / network_info() / version()`.
* `Controller` dataclass: `address`, `model`, `firmware_id`, `version`, `name`,
  `comm_timeouts`, `units`, `status: dict`, `setpoints: dict`, and typed helpers:
  `room_temperature` (special values → `None` + `sensor_fault`), `relay_on`, `mode`,
  `alarms`, `coil_temperature` (if present).
* Always addresses the LDA by IP / sends `Host: <ip>` (the 302 gotcha) and never
  follows redirects.
* Exceptions: `KE2ConnectionError`, `KE2AuthError`, `KE2WriteError`, `KE2ValidationError`.
* Tests: `pytest` + `aioresponses` against `research/samples/`.
* CLI: `python -m pyke2 <ip> status|limits|set <field> <value>` for debugging.

## `ha-ke2` — integration

* **Config flow:** host (IP), username, password (defaults prefilled). It validates by
  calling `/modbus` + `/all`, sets the unique id from the LDA hostname/MAC, and creates
  one HA **device per controller** (via the LDA hub device).
* **Options flow:** poll interval (default 30 s), write confirmation timeout, and
  whether to expose "advanced/dangerous" setpoints.
* **`DataUpdateCoordinator`:** one `/all` per interval. A failure marks entities
  unavailable (`UpdateFailed`). `limits` is fetched once per controller at setup.
* **Entities**, generated from `limits` (so other KE2 models just work):

| Field kind | Entity |
|---|---|
| Room temp + setpoint + relay/mode | `climate` (cool-only; `target_temperature` = setpoint; `hvac_action` cooling / idle / defrosting(off); `hvac_mode` `cool` and, where `Manual Control` exists, `off`) |
| Decimal/Integer Status fields with a unit | `sensor` (temperature, …), special values → unavailable + a diagnostic "sensor fault" |
| Relays (`Relay`, `Compressor/Fan/Defrost Relay`) | `binary_sensor` (running) |
| `SystemMode` | `sensor` (enum) |
| `Alarms` | `binary_sensor` per alarm label (problem) + a count `sensor` with the list as an attribute |
| Editable Integer setpoints | `number` (min/max/step/unit from `limits`) |
| Editable `Table` setpoints | `select` |
| `Time` / `Time_Hours` setpoints | `time` (24:00 → "disabled" via a companion switch) |
| `Manual Control.System Off` | `switch` |
| `GotoNextMode` | `button` |
| Device Info | diagnostic `sensor`s (firmware, comm timeouts) |
| — | `button` "Sync controller clock" (writes `Time of Day` from HA local time) |

* `ModbusAddress` and `Temperature Units` are **disabled by default** and entity
  category `config`, behind the options-flow "advanced" toggle.
* Every write goes through the library (validate → write → re-poll → confirm). A
  mismatch raises `HomeAssistantError`, so automations see the failure.
* `diagnostics.py` dumps `/all` + `limits` (credentials redacted).
* **Not in the integration:** site policy such as the wine-room short-cycle guard, the
  LDA power-cycle watchdog or alerts. They stay as automations on top of these entities.

## Migration of the existing HA YAML (`packages/wine_room.yaml`)

`rest:` sensors → integration sensors. `rest_command` + `script.ke2_set_room_setpoint`
→ `climate.set_temperature` (or `number.set_value`). The guard automations keep their
logic and switch to the new entity ids.
