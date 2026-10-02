"""Async client for KE2 Therm refrigeration controllers via the KE2 LDA network adapter."""

from .client import DEFAULT_PASSWORD, DEFAULT_USERNAME, KE2LDA
from .exceptions import (
    KE2AuthError,
    KE2ConnectionError,
    KE2Error,
    KE2NotSupportedError,
    KE2ValidationError,
    KE2WriteError,
)
from .models import DEVICE_INFO, MANUAL_CONTROL, SETPOINTS, STATUS, Controller, unwrap
from .schema import CELSIUS, FAHRENHEIT, FieldSpec, Schema

__version__ = "0.1.0"

__all__ = [
    "CELSIUS",
    "DEFAULT_PASSWORD",
    "DEFAULT_USERNAME",
    "DEVICE_INFO",
    "FAHRENHEIT",
    "KE2LDA",
    "MANUAL_CONTROL",
    "SETPOINTS",
    "STATUS",
    "Controller",
    "FieldSpec",
    "KE2AuthError",
    "KE2ConnectionError",
    "KE2Error",
    "KE2NotSupportedError",
    "KE2ValidationError",
    "KE2WriteError",
    "Schema",
    "__version__",
    "unwrap",
]
