"""Controller state as returned by ``GET /modbus/<if>/all``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .schema import FAHRENHEIT, Schema

STATUS = "Status"
SETPOINTS = "Setpoints"
DEVICE_INFO = "Device Info"
MANUAL_CONTROL = "Manual Control"

# Status keys for the relay that drives refrigeration, in preference order
# (KE2 Temp: "Relay"; KE2 Low Temp / Adaptive: "Compressor Relay").
_RELAY_KEYS = ("Compressor Relay", "Relay")
# Fallback special values when no schema is available (KE2 Temp limits).
_DEFAULT_SENSOR_FAULTS = {"999.9": "Short Sensor", "888.8": "Open Sensor"}


def unwrap(value: Any) -> Any:
    """Return the plain value of a field ('Dynamic' fields wrap it as {"Value": ...})."""
    if isinstance(value, Mapping) and "Value" in value:
        return value["Value"]
    return value


def _is_on(label: Any) -> bool | None:
    if label is None:
        return None
    text = str(label).lower()
    if text.endswith(" on") or text == "on":
        return True
    if text.endswith(" off") or text == "off":
        return False
    return None


@dataclass
class Controller:
    """One KE2 controller on an LDA Modbus interface."""

    interface: str
    address: int
    model: str
    firmware_id: int | None = None
    version: str | None = None
    device_name: str | None = None
    comm_timeouts: int | None = None
    status: dict[str, Any] = field(default_factory=dict)
    setpoints: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema: Schema | None = None

    @classmethod
    def from_api(cls, interface: str, data: Mapping[str, Any]) -> Controller:
        info = data.get(DEVICE_INFO) or {}
        extra = {
            k: dict(v)
            for k, v in data.items()
            if k not in (STATUS, SETPOINTS, DEVICE_INFO) and isinstance(v, Mapping)
        }
        return cls(
            interface=interface,
            address=int(info.get("address", 0)),
            model=str(info.get("name") or "KE2"),
            firmware_id=info.get("firmware_id"),
            version=info.get("actual_version"),
            device_name=info.get("device_name"),
            comm_timeouts=info.get("commTimeouts"),
            status=dict(data.get(STATUS) or {}),
            setpoints=dict(data.get(SETPOINTS) or {}),
            extra=extra,
        )

    # ── identity ─────────────────────────────────────────────────────────
    @property
    def key(self) -> str:
        """Stable id on the LDA: '<interface>-<address>'."""
        return f"{self.interface}-{self.address}"

    @property
    def endpoint(self) -> str:
        return f"{self.interface}/{self.address}"

    @property
    def title(self) -> str:
        return self.device_name or f"{self.model} {self.address}"

    # ── generic access ───────────────────────────────────────────────────
    def category(self, name: str) -> dict[str, Any]:
        if name == STATUS:
            return self.status
        if name == SETPOINTS:
            return self.setpoints
        return self.extra.get(name, {})

    def value(self, category: str, key: str) -> Any:
        return unwrap(self.category(category).get(key))

    def has(self, category: str, key: str) -> bool:
        return key in self.category(category)

    # ── typed helpers ────────────────────────────────────────────────────
    @property
    def units(self) -> str:
        return str(self.value(SETPOINTS, "Temperature Units") or FAHRENHEIT)

    def _fault(self, category: str, key: str) -> str | None:
        raw = self.value(category, key)
        if raw is None:
            return None
        spec = self.schema.get(category, key) if self.schema else None
        if spec is not None:
            return spec.special_meaning(raw)
        try:
            return _DEFAULT_SENSOR_FAULTS.get(f"{float(raw):.1f}")
        except (TypeError, ValueError):
            return None

    def temperature(self, key: str, category: str = STATUS) -> float | None:
        """A temperature reading, or None when absent or a sensor-fault special value."""
        raw = self.value(category, key)
        if raw is None or self._fault(category, key) is not None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @property
    def room_temperature(self) -> float | None:
        return self.temperature("RoomTemperature")

    @property
    def coil_temperature(self) -> float | None:
        return self.temperature("CoilTemperature")

    @property
    def sensor_fault(self) -> str | None:
        """Special-value meaning of the room probe ('Short Sensor' / 'Open Sensor'), if any."""
        return self._fault(STATUS, "RoomTemperature")

    @property
    def setpoint(self) -> float | None:
        raw = self.value(SETPOINTS, "RoomTemperature")
        return None if raw is None else float(raw)

    @property
    def differential(self) -> float | None:
        raw = self.value(SETPOINTS, "AirTempDiff")
        return None if raw is None else float(raw)

    @property
    def relay_key(self) -> str | None:
        return next((k for k in _RELAY_KEYS if k in self.status), None)

    @property
    def relay_on(self) -> bool | None:
        key = self.relay_key
        return None if key is None else _is_on(self.value(STATUS, key))

    def relay_state(self, key: str) -> bool | None:
        return _is_on(self.value(STATUS, key))

    @property
    def mode(self) -> str | None:
        raw = self.value(STATUS, "SystemMode")
        return None if raw is None else str(raw)

    @property
    def defrosting(self) -> bool:
        return (self.mode or "").lower() == "defrost"

    @property
    def alarms(self) -> list[str]:
        raw = self.value(STATUS, "Alarms")
        if raw is None:
            return []
        if isinstance(raw, list | tuple):
            return [str(a) for a in raw]
        return [str(raw)] if raw else []

    @property
    def supports_manual_control(self) -> bool:
        return "System Off" in self.extra.get(MANUAL_CONTROL, {})

    @property
    def system_on(self) -> bool | None:
        """Manual Control state (None on models without it)."""
        raw = self.value(MANUAL_CONTROL, "System Off")
        if raw is None:
            return None
        return str(raw) != "Modbus Off"
