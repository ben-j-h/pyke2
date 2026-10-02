"""The controller's self-describing field schema (``GET /modbus/<if>/<addr>/limits``).

Every field has a descriptor::

    {"Editable": true, "DataType": "Integer", "ShowUnit": "Temperature",
     "Options": {"Min": {"Fahrenheit": 1, "Celsius": 1}, "Max": {...},
                 "Discrete": [...], "Special Values": {"0": "Disabled"}}}

See ``research/02-data-model.md``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from .exceptions import KE2NotSupportedError, KE2ValidationError

FAHRENHEIT = "Fahrenheit"
CELSIUS = "Celsius"

DT_INTEGER = "Integer"
DT_DECIMAL = "Decimal"
DT_TABLE = "Table"
DT_TABLE_BITMAP = "Table-Bitmap"
DT_BITMAP = "Bitmap"
DT_TIME = "Time"
DT_TIME_HOURS = "Time_Hours"
DT_DYNAMIC = "Dynamic"

ENUM_TYPES = frozenset({DT_TABLE, DT_TABLE_BITMAP})
TIME_TYPES = frozenset({DT_TIME, DT_TIME_HOURS})
NUMERIC_TYPES = frozenset({DT_INTEGER, DT_DECIMAL})

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _special_key(value: Any) -> list[str]:
    """String forms a value may take as a key in ``Special Values`` ("999.9", "0", "24:00")."""
    keys = [str(value)]
    if isinstance(value, float):
        keys += [f"{value:.1f}", f"{value:g}"]
        if value.is_integer():
            keys.append(str(int(value)))
    elif isinstance(value, int) and not isinstance(value, bool):
        keys.append(f"{float(value):.1f}")
    return keys


def _time_minutes(value: str) -> int:
    match = _TIME_RE.match(value.strip())
    if not match:
        raise KE2ValidationError(f"{value!r} is not a HH:MM time")
    hours, minutes = int(match.group(1)), int(match.group(2))
    if minutes > 59:
        raise KE2ValidationError(f"{value!r} has invalid minutes")
    return hours * 60 + minutes


@dataclass(frozen=True)
class FieldSpec:
    """Descriptor of one controller field."""

    category: str
    key: str
    editable: bool
    data_type: str
    show_unit: str | None = None
    min: Any = None
    max: Any = None
    discrete: tuple[Any, ...] = ()
    special_values: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_descriptor(cls, category: str, key: str, desc: Mapping[str, Any]) -> FieldSpec:
        options = desc.get("Options") or {}
        return cls(
            category=category,
            key=key,
            editable=bool(desc.get("Editable", False)),
            data_type=str(desc.get("DataType", "")),
            show_unit=desc.get("ShowUnit"),
            min=options.get("Min"),
            max=options.get("Max"),
            discrete=tuple(options.get("Discrete") or ()),
            special_values=dict(options.get("Special Values") or {}),
        )

    @property
    def is_temperature(self) -> bool:
        return self.show_unit == "Temperature"

    @property
    def is_enum(self) -> bool:
        return self.data_type in ENUM_TYPES

    @property
    def is_time(self) -> bool:
        return self.data_type in TIME_TYPES

    @property
    def is_numeric(self) -> bool:
        return self.data_type in NUMERIC_TYPES

    @property
    def options(self) -> list[str]:
        """Labels for enum fields."""
        return [str(v) for v in self.discrete] if self.is_enum else []

    def _resolve(self, bound: Any, units: str) -> Any:
        if isinstance(bound, Mapping):
            return bound.get(units, bound.get(FAHRENHEIT))
        return bound

    def bounds(self, units: str = FAHRENHEIT) -> tuple[Any, Any]:
        """(min, max) in the controller's current units (numbers or HH:MM strings)."""
        return self._resolve(self.min, units), self._resolve(self.max, units)

    def special_meaning(self, value: Any) -> str | None:
        """Meaning of a special value (e.g. 999.9 → 'Short Sensor'), else None."""
        if value is None or not self.special_values:
            return None
        for key in _special_key(value):
            if key in self.special_values:
                return self.special_values[key]
        return None

    def validate(self, value: Any, units: str = FAHRENHEIT) -> Any:
        """Check ``value`` for writing and return it normalised for the API.

        Raises KE2ValidationError when it is outside the schema.
        """
        if not self.editable:
            raise KE2ValidationError(f"{self.category}.{self.key} is read-only")

        if self.is_enum:
            label = str(value)
            if self.discrete and label not in self.options:
                raise KE2ValidationError(f"{self.key}: {label!r} not one of {self.options}")
            return label

        if self.is_time:
            text = str(value).strip()
            if self.special_meaning(text) is not None:
                return text
            minutes = _time_minutes(text)
            lo, hi = self.bounds(units)
            lo_m = _time_minutes(lo) if lo else 0
            hi_m = _time_minutes(hi) if hi else 23 * 60 + 59
            if not lo_m <= minutes <= hi_m:
                raise KE2ValidationError(f"{self.key}: {text} outside {lo}-{hi}")
            return f"{minutes // 60:02d}:{minutes % 60:02d}"

        if self.is_numeric:
            try:
                number = float(value)
            except (TypeError, ValueError) as err:
                raise KE2ValidationError(f"{self.key}: {value!r} is not a number") from err
            if self.data_type == DT_INTEGER:
                if not number.is_integer():
                    raise KE2ValidationError(f"{self.key}: {value!r} must be a whole number")
                number = int(number)
            if self.special_meaning(number) is not None:
                return number
            if any(number == d for d in self.discrete if isinstance(d, int | float)):
                return number
            lo, hi = self.bounds(units)
            if (lo is not None and number < lo) or (hi is not None and number > hi):
                raise KE2ValidationError(f"{self.key}: {number} outside {lo}-{hi} ({units})")
            return number

        raise KE2ValidationError(f"{self.key}: writing {self.data_type!r} fields is not supported")


class Schema:
    """All field descriptors of one controller, by category then key."""

    def __init__(self, fields: Mapping[str, Mapping[str, FieldSpec]]) -> None:
        self._fields = {cat: dict(keys) for cat, keys in fields.items()}

    @classmethod
    def from_limits(cls, limits: Mapping[str, Any]) -> Schema:
        fields: dict[str, dict[str, FieldSpec]] = {}
        for category, keys in limits.items():
            if not isinstance(keys, Mapping):
                continue
            fields[category] = {
                key: FieldSpec.from_descriptor(category, key, desc)
                for key, desc in keys.items()
                if isinstance(desc, Mapping)
            }
        return cls(fields)

    @property
    def categories(self) -> list[str]:
        return list(self._fields)

    def get(self, category: str, key: str) -> FieldSpec | None:
        return self._fields.get(category, {}).get(key)

    def require(self, category: str, key: str) -> FieldSpec:
        spec = self.get(category, key)
        if spec is None:
            raise KE2NotSupportedError(f"controller has no field {category}.{key}")
        return spec

    def fields(self, category: str | None = None) -> Iterator[FieldSpec]:
        for cat, keys in self._fields.items():
            if category is None or cat == category:
                yield from keys.values()

    def editable(self) -> Iterator[FieldSpec]:
        return (f for f in self.fields() if f.editable)

    def __contains__(self, item: tuple[str, str]) -> bool:
        return self.get(*item) is not None
