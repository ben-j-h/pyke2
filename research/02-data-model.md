# 02 — Data model

## Payload shape

`GET /modbus/COM1/all` → one object per controller on the bus:

```json
[{
  "Status":   {"Relay": "Relay On", "RoomTemperature": 57.1, "SystemMode": "Refrigerate", "Alarms": []},
  "Setpoints":{"RoomTemperature": 55, "AirTempDiff": 5, "DefrostsPerDay": 2, "Defrost Time": 20, "...": "..."},
  "Device Info": {"address": 1, "name": "KE2 Temp", "firmware_id": 20643, "actual_version": "1.11",
                  "device_name": null, "commTimeouts": 0}
}]
```

Values come in the **controller's configured unit** (`Setpoints."Temperature Units"`,
`Fahrenheit` | `Celsius`). Enumerated fields come as their **label strings**, not raw
register values.

## The `limits` schema

`GET /modbus/COM1/<addr>/limits` mirrors the payload, with one descriptor per field:

```json
"AirTempDiff": {
  "Editable": true,
  "DataType": "Integer",
  "ShowUnit": "Temperature",
  "Options": {"Min": {"Fahrenheit": 1, "Celsius": 1}, "Max": {"Fahrenheit": 30, "Celsius": 17}}
}
```

| Key | Meaning |
|-----|---------|
| `Editable` | Writable via `PUT …/<Category>` |
| `DataType` | `Integer`, `Decimal`, `Table` (enum, value = label), `Table-Bitmap` (enum), `Bitmap` (list of active labels, e.g. `Alarms`), `Time` (`HH:MM`, 00:00–23:59), `Time_Hours` (`HH:MM`, 00:00–24:00), `Dynamic` (see below) |
| `ShowUnit` | `Temperature` → `Min`/`Max` are per-unit objects keyed `Fahrenheit` / `Celsius`. Absent → plain numbers |
| `Options.Min` / `Max` | Range (number, per-unit object, or `HH:MM` string) |
| `Options.Discrete` | Allowed labels (enums), or extra allowed values outside Min/Max (e.g. `[0]`) |
| `Options."Special Values"` | Value → meaning, e.g. `"24:00": "Disabled"`, `"0": "Disabled"`, `"13": "Custom"`, `"999.9": "Short Sensor"`, `"888.8": "Open Sensor"` |

**`Dynamic` fields** carry their own descriptor in the *data* payload instead of in
`limits`: `{"Value": …, "Options": {…}, "ShowUnit": …}` (from `service_view.js`
`isDynamicField`). None of these exist on the KE2 Temp. A client must unwrap `Value`.

**Special values must be handled before range checks.** A room temperature of `999.9`
or `888.8` is a sensor fault, not a reading.

## KE2 Temp field dictionary (fw 20643 v1.11)

### Status (read-only)

| Field | Type | Values |
|-------|------|--------|
| `RoomTemperature` | Decimal, °unit | Air probe. `999.9` = sensor short, `888.8` = sensor open |
| `Relay` | Table | `Relay Off` / `Relay On`, the single compressor/solenoid output |
| `SystemMode` | Table-Bitmap | `Unknown`, `Refrigerate`, `Off` (satisfied/idle), `Defrost` |
| `Alarms` | Bitmap | list of: `Air Temp Sensor Open`, `Air Temp Sensor Short`, `High Air Temp`, `Low Air Temp` |

### Setpoints (writable)

| Field | Type | Range | Notes |
|-------|------|-------|-------|
| `RoomTemperature` | Integer, °unit | −50…100 °F / −45…38 °C | Cut-out. Observed cut-in ≈ setpoint + `AirTempDiff` |
| `AirTempDiff` | Integer, °unit | 1…30 °F / 1…17 °C | Differential |
| `Compressor Starts Per Hour` | Integer | 5…10, or `0` = Disabled | Anti-short-cycle limit on the **relay**. It cannot stop a condensing unit's own pressure-switch cycling |
| `DefrostsPerDay` | Integer | 0…12, `13` = Custom | Off-cycle defrosts. 13 → the `Start Time of Defrost 1…12` schedule is used |
| `Defrost Time` | Integer (min) | 0…720 | Defrost duration |
| `Start Time of Defrost 1…12` | Time_Hours | 00:00…24:00, `24:00` = Disabled | Only used when `DefrostsPerDay == 13` (the UI hides them otherwise) |
| `Time of Day` | Time | 00:00…23:59 | Controller clock. Free-running; the UI hides it unless the schedule is custom |
| `HiTempAlarmOffset` / `LowTempAlarmOffset` | Integer, °unit | 1…10 °F / 1…6 °C | Alarm band around the setpoint |
| `HighAndLowAlarmDelay` | Integer (min) | 1…180 | |
| `ModbusAddress` | Integer | 1…247 | **Dangerous.** Changing it moves the controller on the bus. Never expose as a casual control |
| `Temperature Units` | Table | `Fahrenheit` / `Celsius` | Changes the unit of every temperature field |

### Device Info (read-only)

`address`, `name` (model), `firmware_id`, `actual_version`, `device_name` (user label,
null here), `commTimeouts` (LDA↔controller Modbus timeouts).

## Other models (from the web app; not seen live)

`service_view.js` special-cases the status layout per model:

| Model (`Device Info.name`) | Status fields |
|---|---|
| `KE2 Temp` | `SystemMode`, `RoomTemperature`, `Relay`, `Alarms` |
| `KE2 Low Temp`, `KE2 Adaptive` | `SystemMode`, `RoomTemperature`, `CoilTemperature`, `Compressor Relay`, `Fan Relay`, `Defrost Relay`, `AuxInput3`, `AuxInput4`, `Alarms` |
| anything else | all `Status` keys, natural-sorted |

Any model may expose a `Manual Control` category with `System Off` (`Modbus Off` /
`System On`). The UI shows a "Turn System Off/On" button when it is present. Because the
library and integration are driven by `limits`, they handle all of these generically.
