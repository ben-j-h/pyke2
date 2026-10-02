# 03 — Live test results

Controller: KE2 Temp fw 20643 v1.11 at Modbus address 1, LDA V1.3.2, on a wine-room
cooler (split system, outdoor condensing unit). Compressor power is measured
independently by a Brultech GEM on its circuit (about 7 s samples), so every write's
physical effect is confirmed, not just the API's reply.

## Reads

| Test | Result |
|------|--------|
| `GET /modbus/COM1/all` unauthenticated, every 30 s for days | Works. About 1.3 KB, typically < 100 ms |
| Same, with `Host: KE2LDA-xxxxxx.<domain>` | `302` → `https://ke2lda.ke2.co/modbus/COM1/all`. A client following redirects times out (`rest` integration: "Timeout while fetching data") |
| `GET …/1/Manual%20Control` on KE2 Temp | `404 Device Not Found`. The category doesn't exist on this model |
| LDA availability (2026-09-30 → 10-01 night) | 9 dropouts of about 30 s, all self-recovered |

## Writes

| Date (PT) | Request | API reply | Physical effect |
|-----------|---------|-----------|-----------------|
| 2026-10-02 05:56:47 | `PUT /modbus/COM1/1/Setpoints {"RoomTemperature":60}` (room 57.1 °F, compressor short-cycling) | `{"Status":200,"Message":"Success","Details":"Data Successfully written"}` | Read-back `60` and `Relay Off` / mode `Off` by 05:56:57. Compressor circuit fell 900 W → 120 W (fan only) by 05:57:00 |
| 2026-10-02 07:10:30 | `PUT …/Setpoints {"Time of Day":"07:10"}` via ha-ke2 *Sync controller clock* | `Success` | Read-back still `08:46` after ~10 s (ha-ke2 0.1.0 raised "not confirmed"); `07:10` by 07:11:18. **Clock writes apply ~10–40 s late.** ha-ke2 0.1.1 re-polls up to ~30 s |
| 2026-10-02 06:00:33 | Same via HA `rest_command` (`Cookie: modbusSessionID=…`), value unchanged (60) | `Success` | n/a (no-op), confirms the HA write path |

**Latency:** setpoint write → relay change ≤ 10 s, read-back ≤ 10 s. `Time of Day` read-back
took longer (> 10 s, < 50 s). Confirm writes by re-polling, not with a single read.

## Behaviour notes

* **Cut-in/cut-out:** with setpoint 55 and differential 5, the relay came on near 60 °F
  and dropped at 55 °F. So the setpoint is the cut-out and the cut-in is setpoint + diff.
* **`Compressor Starts Per Hour`** (6 here) limits *relay* starts only. With the relay
  held on continuously, the condensing unit's own low-pressure control restarted the
  compressor about 515 times in one night. The KE2 neither sees nor limits that.
* **Defrost** (`DefrostsPerDay` 2, `Defrost Time` 20): shows as `SystemMode = Defrost`
  with `Relay Off` for 20 min.
* **Clock:** `Time of Day` read 19:11 at 17:35 PDT and 07:48 at 06:13 PDT the next day.
  That's a stable +1 h 35 min offset (set by hand; no NTP). It matters only for custom
  defrost schedules.

## Not yet tested

* `POST …/GotoNextMode`: expected to step Refrigerate → Off → Defrost. Test when a
  forced defrost is harmless.
* Session lifetime / expiry, and concurrent sessions.
* Writing `Temperature Units`, `DefrostsPerDay = 13` + schedule.
* What `/all` returns when the LDA has lost the Modbus link (no capture yet).
