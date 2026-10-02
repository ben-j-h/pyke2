"""Fixtures built from responses captured from a real KE2 Temp + LDA (research/samples)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SAMPLES = Path(__file__).parent.parent / "research" / "samples"
IP = "192.168.30.165"
BASE = f"http://{IP}"


def load(name: str):
    return json.loads((SAMPLES / name).read_text())


@pytest.fixture
def all_payload():
    return load("modbus_COM1_all.json")


@pytest.fixture
def limits_payload():
    return load("modbus_COM1_1_limits.json")


@pytest.fixture
def controller_payload():
    return load("modbus_COM1_1.json")
