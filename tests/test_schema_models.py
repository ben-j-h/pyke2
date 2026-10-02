from __future__ import annotations

import pytest

from pyke2 import CELSIUS, Controller, KE2NotSupportedError, KE2ValidationError, Schema


@pytest.fixture
def schema(limits_payload) -> Schema:
    return Schema.from_limits(limits_payload)


def test_schema_categories(schema):
    assert set(schema.categories) == {"Status", "Setpoints"}
    assert len(list(schema.editable())) == 23
    assert not schema.require("Status", "Relay").editable


def test_room_setpoint_range_per_unit(schema):
    spec = schema.require("Setpoints", "RoomTemperature")
    assert spec.is_temperature
    assert spec.bounds() == (-50, 100)
    assert spec.bounds(CELSIUS) == (-45, 38)
    assert spec.validate(60) == 60
    assert spec.validate("55") == 55
    with pytest.raises(KE2ValidationError):
        spec.validate(101)
    with pytest.raises(KE2ValidationError):
        spec.validate(55.5)
    with pytest.raises(KE2ValidationError):
        spec.validate(40, CELSIUS)


def test_special_and_discrete_values(schema):
    starts = schema.require("Setpoints", "Compressor Starts Per Hour")
    assert starts.validate(0) == 0  # special: Disabled
    assert starts.validate(6) == 6
    with pytest.raises(KE2ValidationError):
        starts.validate(3)
    defrosts = schema.require("Setpoints", "DefrostsPerDay")
    assert defrosts.special_meaning(13) == "Custom"


def test_time_fields(schema):
    start = schema.require("Setpoints", "Start Time of Defrost 1")
    assert start.validate("24:00") == "24:00"  # Disabled
    assert start.validate("6:05") == "06:05"
    clock = schema.require("Setpoints", "Time of Day")
    assert clock.validate("23:59") == "23:59"
    with pytest.raises(KE2ValidationError):
        clock.validate("24:00")
    with pytest.raises(KE2ValidationError):
        clock.validate("12:60")


def test_enum_fields(schema):
    units = schema.require("Setpoints", "Temperature Units")
    assert units.is_enum and units.options == ["Fahrenheit", "Celsius"]
    assert units.validate("Celsius") == "Celsius"
    with pytest.raises(KE2ValidationError):
        units.validate("Kelvin")


def test_read_only_and_missing(schema):
    with pytest.raises(KE2ValidationError):
        schema.require("Status", "RoomTemperature").validate(50)
    with pytest.raises(KE2NotSupportedError):
        schema.require("Manual Control", "System Off")


def test_controller_from_all(all_payload, limits_payload):
    ctrl = Controller.from_api("COM1", all_payload[0])
    ctrl.schema = Schema.from_limits(limits_payload)
    assert ctrl.key == "COM1-1"
    assert ctrl.model == "KE2 Temp"
    assert ctrl.units == "Fahrenheit"
    assert isinstance(ctrl.room_temperature, float)
    assert ctrl.sensor_fault is None
    assert ctrl.relay_key == "Relay"
    assert ctrl.relay_on in (True, False)
    assert ctrl.mode in ("Refrigerate", "Off", "Defrost")
    assert ctrl.alarms == []
    assert ctrl.supports_manual_control is False
    assert ctrl.system_on is None


def test_sensor_fault_special_values(all_payload, limits_payload):
    data = dict(all_payload[0])
    data["Status"] = {**data["Status"], "RoomTemperature": 999.9}
    ctrl = Controller.from_api("COM1", data)
    assert ctrl.room_temperature is None
    assert ctrl.sensor_fault == "Short Sensor"  # default table, no schema
    ctrl.schema = Schema.from_limits(limits_payload)
    data["Status"]["RoomTemperature"] = 888.8
    ctrl = Controller.from_api("COM1", data)
    ctrl.schema = Schema.from_limits(limits_payload)
    assert ctrl.sensor_fault == "Open Sensor"


def test_other_models_and_dynamic_fields():
    ctrl = Controller.from_api(
        "COM1",
        {
            "Device Info": {"address": 3, "name": "KE2 Adaptive"},
            "Status": {
                "Compressor Relay": "Compressor Relay On",
                "Fan Relay": "Fan Relay Off",
                "CoilTemperature": {"Value": 21.5},
                "RoomTemperature": 34.0,
                "SystemMode": "Defrost",
                "Alarms": ["High Air Temp"],
            },
            "Setpoints": {"RoomTemperature": 35},
            "Manual Control": {"System Off": "Modbus Off"},
        },
    )
    assert ctrl.relay_key == "Compressor Relay" and ctrl.relay_on is True
    assert ctrl.relay_state("Fan Relay") is False
    assert ctrl.coil_temperature == 21.5
    assert ctrl.defrosting
    assert ctrl.alarms == ["High Air Temp"]
    assert ctrl.supports_manual_control and ctrl.system_on is False
