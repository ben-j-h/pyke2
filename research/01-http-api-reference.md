# 01 — HTTP API reference (KE2 LDA V1.3.2)

Base URL: `http://<LDA IP>` (**IP only**, see *Host header* below). All bodies are JSON.
`<if>` = Modbus interface (`COM1`), `<addr>` = controller Modbus address (1–247).
Sources: `raw/smartaccess_modbus_js_device_api.js`, `raw/dashboard_client_client.js`,
plus live calls.

## Discovery (no auth)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/modbus` | `["COM1"]`, the interfaces |
| GET | `/modbus/<if>` | `[{address, name, firmware_id, actual_version, device_name, commTimeouts}]`, one per controller on the bus |
| GET | `/version.json` | LDA build info (`Version`, `Build Time`, `Commit Hash`, …) |
| GET | `/smartaccess/client/exec/networkInfo.lua` | `{"wan-fqdn", "wlan1", "br-lan"}`, interface IPs |

## Read (no auth)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/modbus/<if>/all` | `[ {Status, Setpoints, "Device Info"} … ]` for **every** controller. One call per poll. |
| GET | `/modbus/<if>/<addr>` | `{Status, Setpoints, "Device Info"}` for one controller |
| GET | `/modbus/<if>/<addr>/<Category>` | `{<Category>: {…}}`. Categories: `Status`, `Setpoints`, `Device Info`, and on some models `Manual Control` |
| GET | `/modbus/<if>/<addr>/limits` | The field schema (see [02](02-data-model.md)) |

A category the model doesn't have → HTTP 404
`{"Status":404,"Message":"Device Not Found","Details":"The device requested is not present"}`.

`Device Info.commTimeouts` counts Modbus timeouts between the LDA and that controller.
It is the LDA-side signal of a flaky RS-485 link.

## Auth

```
POST /auth/login
{"action":"login","role":"modbus","username":"ke2admin","password":"ke2admin"}
→ {"status":"success","message":"logged in","sessionID":"<32 chars>"}
→ {"status":"failed","message":"incorrect username or password"}

POST /auth/getSessionInfo   {"action":"getSessionInfo","sessionID":"…"}
→ {"username":"ke2admin","role":"modbus","status":"success"}

POST /auth/logout           {"action":"logout","sessionID":"…"}
```

Roles seen in the UI: `modbus` (controller writes), `mgmt` (LDA settings, firewall,
updates), `wifi`. The `modbus` session is carried as cookie **`modbusSessionID`**. The
`mgmt` session is cookie **`mgmtSessionID`**, or `?SID=` on `exec/run.txt` commands.

## Write (needs `modbusSessionID`)

| Method | Path | Body | Effect |
|--------|------|------|--------|
| PUT | `/modbus/<if>/<addr>/Setpoints` | `{"<field>": <value>}` (one or more fields) | Writes setpoints → `{"Status":200,"Message":"Success","Details":"Data Successfully written"}` |
| PUT | `/modbus/<if>/<addr>/Manual%20Control` | `{"System Off": "Modbus Off" \| "System On"}` | System off/on (**not on KE2 Temp**) |
| POST | `/modbus/<if>/<addr>/GotoNextMode` | none | Advance the operating mode (UI "Next Mode" button). *Not yet live-tested.* |

The web UI calls `getSessionInfo` before every write and re-prompts on failure. The
session lifetime is not measured yet. A client should re-login on any auth failure.

## LDA management (mgmt role, out of scope for the integration)

From `client.js`: `/smartaccess/client/exec/firewall/{wanAccessStatus,enableWanAccess,disableWanAccess}`,
`/root/connect/{wifi,scan,checkTetherDisconnect}` (Wi-Fi tether),
`/update/{checkConnection,latestVersionInfo,downloadUpgrade,verifyDownload,launchUpgrade}`
(firmware update from KE2 cloud), `/smartaccess/client/datalog.csv?…` and
`exec/checkLoggerStatus` (an on-box data logger, off on ours), `/auth/getUsersAndRoles`.
`wanAccessStatus` returned `1` with a `mgmt` session.

## Host header

nginx answers `302 Location: https://ke2lda.ke2.co/<path>` to any request whose `Host`
isn't the LDA's IP. That includes its own DHCP hostname `KE2LDA-xxxxxx.<domain>`.
Clients must use the IP, or send `Host: <ip>`.

## Error / flakiness behaviour

* LDA unreachable: TCP connect timeout. In practice it drops off for about 30 s several
  times a night, then recovers by itself.
* Lost Modbus link: TBD. We expect empty arrays or 404s from `/all` and rising
  `commTimeouts`. An HA watchdog power-cycles the LDA when no valid reading arrives for
  10 min. Record what this looks like when it happens.
