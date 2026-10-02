# 05 — Direct Modbus (skipping the LDA)

**Status: research only, nothing built.** Parked until the author's wine-room unit is
repaired or replaced (2026-10-02). This page records what is known and the plan.

The LDA is the weak link in practice: Wi-Fi dropouts, lost Modbus links that need a hard
power-cycle, a cloud redirect on non-IP hosts, and 2017 firmware. Under it, the controllers
speak plain **Modbus RTU over RS-485**. The LDA is only the bus master plus a JSON
front-end that relabels registers. Replacing it with an ESP32 running ESPHome
(`modbus_controller`) would remove all of that.

## What is known

### From KE2's own documents

| Source | What it gives |
|---|---|
| KE2 Temp + Air Defrost operation manual Q.3.20 (Dec 2020) — [uri.com copy](https://www.uri.com/INTERSHOP/static/BOS/URI-URIUS-Site/-/URI/en_US/manuals/OM-KE2-Temp-Air-Defrost.pdf) | "Serial-Modbus controllers: KE2 Temp, KE2 Low Temp, KE2 Adaptive Control". RS-485 to a **KE2 LDA** (*Local Area Dashboard and Alarms*) or **KE2 Edge Manager (EM)**. Cat5e, using the **blue/white pair**. Controller powered from **120 V or 208–240 V mains** (voltage selector switch). |
| KE2 Temp setpoint sheet — [uri.com copy](https://www.uri.com/INTERSHOP/static/BOS/URI-URIUS-Site/-/URI/en_US/manuals/SM-KE2-Temp-Air-Defrost.pdf) | `Adr` = Modbus address, default 1, range 1–247 (matches `Setpoints.ModbusAddress`) |
| **"F-1-12 KE2 Temp Modbus Communications", March 2019** | The real register map. Once shared publicly via a Dropbox link that is now dead. **Ask KE2 for it** (ke2therm.com support, 636-266-0140) |

No public source gives baud rate, parity or holding-register addresses.

### From an integrator thread ([AutomationDirect community](https://community.automationdirect.com/s/question/0D53u00004MesT1CAJ/interfacing-to-a-ke2therm-thermostat-defrost-controller-modbus-questions))

* Read **3 input registers starting at 30001** (function code **04**), 16-bit, slave address 1.
* System status bitmap: bit 0 = Cool, bit 1 = Off, bit 2 = Defrost.
* Alarm bitmap: bit 0 = sensor open, bit 1 = sensor short, bit 2 = high temp, bit 3 = low temp.
* Setpoint and defrost changes are writes to holding registers (addresses not given).
* One user found the KE2's **A/B terminal labelling reversed** compared with AutomationDirect's.

These bitmaps match the LDA's `limits` exactly: `SystemMode` (`Table-Bitmap`) is `Unknown, Refrigerate, Off, Defrost`, and `Alarms` (`Bitmap`) is `Air Temp Sensor Open, Air Temp Sensor Short, High Air Temp, Low Air Temp`, in the same bit order. So the LDA's field list is a reliable guide to the register list. Each `limits` entry very likely maps to one register, with the LDA translating
bitmaps and tables into labels.

### Working hypothesis for the KE2 Temp

| Register (FC) | Likely content | Confirm by |
|---|---|---|
| 30001 (04) | System status bitmap (`SystemMode`) | capture |
| 30002 (04) | Alarm bitmap (`Alarms`) | capture |
| 30003 (04) | Room temperature, probably ×10 signed (`999.9` / `888.8` = probe short / open) | capture vs the LDA's value |
| 4xxxx (03/06/16) | One holding register per `Setpoints` field: setpoint, differential, defrosts/day, defrost time, start times (`HH:MM` probably as minutes or HHMM), clock, alarm offsets/delay, starts/hour, address, units | write each field once via the LDA, watch which register changes |
| ? | Relay state | maybe a status bit, maybe its own register |

## How to get the map

1. **Ask KE2 for F-1-12.** It is authoritative, and gives scaling and the registers the LDA
   never touches.
2. **Passive capture** on the existing bus with the LDA still in place:
   * Hardware: a TTL↔RS-485 transceiver (MAX3485 for 3.3 V / MAX485 for 5 V, ~$2) on the
     author's **DSD TECH SH-U09C** (FT232RL USB-TTL, jumper set to match), or any USB RS-485
     dongle.
   * Wiring: A/B in parallel on the blue/white pair (swap if the frames don't decode), RO →
     adapter RX, **DE and /RE tied to GND**. That forces the transceiver into receive-only, so it
     can never drive the bus or disturb the LDA.
   * Capture a few minutes of the LDA's polling (it reads every controller continuously), then
     make one setpoint write per field through HA / `python -m pyke2 <ip> set …` and record
     which holding register each write hits. Try 9600 8N1 first, then 19200 / 38400 and
     8E1 / 8N2.
   * Planned probe script: `research/probe/rs485_sniff.py`. It would decode RTU frames (CRC16,
     FC 03/04/06/16), pair requests with responses, and diff register values against
     `GET /modbus/COM1/all` taken at the same moment.

## Target architecture without the LDA

* **ESP32 + RS-485 transceiver running ESPHome** (`uart` + `modbus` + `modbus_controller`) as the
  bus master. For example an M5Stack NanoC6 plus an M5 RS485 unit, the same component family
  as the author's fountain M5 Tough nodes. No fallback AP / captive portal.
* **Power: not from the KE2.** The KE2 Temp is mains-powered and its RS-485 terminals are
  data-only. A mains-to-5 V converter inside a line-voltage controller housing in a cold, humid
  room (UL listing, warranty, condensation, heat) is not recommended. Mount the ESP32 in its own
  small box beside the controller, USB-powered from the smart plug that powers the LDA today.
  That keeps remote power-cycling and reuses the outlet.
* Entities come straight from ESPHome. A published `esphome/ke2-temp.yaml` package in
  `ha-ke2` would serve owners who want to drop the LDA. `pyke2` + `ha-ke2` remain the path
  for LDA owners. Optionally, pyke2 later gains a Modbus transport behind the same `Schema`.
* **Only one bus master.** The LDA must be disconnected from the bus once the ESP32 takes over.
