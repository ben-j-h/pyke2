# KE2 Therm controllers via the KE2 LDA — Reverse-Engineering Notes

Target: a **KE2 Temp** refrigeration thermostat (Modbus address 1, firmware id 20643,
version 1.11) on RS-485 behind a **KE2 LDA** (Local Device Adapter) network bridge,
LDA software **V1.3.2** (build 2017-05-05, commit `36a30eb`).

Captured 2026-09-30 → 2026-10-02 against `http://192.168.30.165` (an LDA on a
wine-room cooler). Raw web-app bundles are in `raw/` (vendor code, git-ignored);
captured responses are in `samples/`.

---

## TL;DR — what we found

* The LDA is a small **OpenWrt** box running **nginx 1.10.2**. It bridges one RS-485
  Modbus bus (`COM1`) to a **JSON REST API**. The web UI ("SmartAccess") is a
  Mithril.js single-page app that is a thin client over that API.
* **Reads need no authentication.** `GET /modbus/COM1/all` returns every controller on
  the bus with `Status`, `Setpoints` and `Device Info` in about 1 KB.
* **Writes need a session.** `POST /auth/login` (role `modbus`) returns a `sessionID`.
  Send it as the cookie `modbusSessionID` on `PUT /modbus/COM1/<addr>/<Category>`.
  A write is applied by the controller within about 10 s.
* **The API describes itself.** `GET /modbus/COM1/<addr>/limits` returns, for every
  field: editable or not, data type, unit class, min/max per unit, discrete options and
  "special values". An integration can be driven entirely by this schema, so other KE2
  models work without hard-coding.
* There are **three controller families** in the web app: *KE2 Temp* (this one),
  *KE2 Low Temp* and *KE2 Adaptive*. The last two add coil temperature, compressor, fan
  and defrost relays, and aux inputs.
* There are two control verbs besides setpoints. `POST …/GotoNextMode` cycles the
  operating mode (Refrigerate → Off → Defrost). `PUT …/Manual Control`
  `{"System Off": "Modbus Off" | "System On"}` is a true on/off, but it **is not present
  on the KE2 Temp** (`404 Device Not Found`).
* **Gotcha:** nginx **302-redirects any request whose `Host` header is not the LDA's IP**
  to `https://ke2lda.ke2.co/…` (KE2's cloud). Using the LDA's hostname makes clients time
  out or leave the LAN. **Always address the LDA by IP.**
* **The LDA's LAN port runs a DHCP server** (`br-lan` 192.168.50.1/24). Never cable it
  into a house network. The WAN port is the uplink, or use Wi-Fi "tether" mode.
* **The LDA is flaky.** It drops off the network or loses its Modbus link now and then.
  Real-world recovery is a hard power-cycle (we use a smart plug plus an HA watchdog).

**Conclusion:** a pure-Python, local-polling HA integration is straightforward. See
[`04-home-assistant-architecture.md`](04-home-assistant-architecture.md).

## Documents in this folder

| File | Contents |
|------|----------|
| [`01-http-api-reference.md`](01-http-api-reference.md) | Every endpoint, auth flow, request/response shapes, errors |
| [`02-data-model.md`](02-data-model.md) | The `limits` schema, data types, special values, per-model fields, the KE2 Temp field dictionary |
| [`03-live-test-results.md`](03-live-test-results.md) | What writes actually did on the real controller, timings, quirks |
| [`04-home-assistant-architecture.md`](04-home-assistant-architecture.md) | Library + integration design, entity mapping |
| `samples/` | Captured JSON responses (fixtures for the library's tests) |
| `raw/` | Downloaded LDA web-app bundles used for the RE (git-ignored, vendor code) |

## Device facts captured

| Thing | Value |
|-------|-------|
| HTTP server | `nginx/1.10.2` |
| LDA software | `V1.3.2`, build 2017-05-05T23:16:56Z, commit `36a30eb50afa` (`/version.json`) |
| Open ports | 80, 443. Closed: 22, 23, 502 (no Modbus TCP), 1883, 8080 |
| Interfaces | `wlan1` (Wi-Fi client, "tether"), WAN (wired uplink), `br-lan` 192.168.50.1/24 (DHCP server) |
| Hostname | `KE2LDA-<6 hex>` (last 3 bytes of the MAC) |
| Modbus | one bus, `COM1`. Controllers addressed 1–247 |
| Controller | KE2 Temp, fw id 20643, v1.11, address 1 |
| Default credentials | `ke2admin` / `ke2admin` (roles: `mgmt`, `modbus`, `wifi`) |
| Controller clock | Free-running, set by hand. Ours read +1 h 35 min fast (stable over 24 h) |
