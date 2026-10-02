from __future__ import annotations

import json
import re

import pytest
from aioresponses import aioresponses
from conftest import BASE, IP

from pyke2 import (
    KE2LDA,
    KE2AuthError,
    KE2ConnectionError,
    KE2NotSupportedError,
    KE2ValidationError,
    KE2WriteError,
)

LOGIN_OK = {"status": "success", "message": "logged in", "sessionID": "abc123"}
WRITE_OK = {"Status": 200, "Message": "Success", "Details": "Data Successfully written"}


@pytest.fixture
def mocked():
    with aioresponses() as m:
        yield m


def _reads(m, all_payload, controller_payload, limits_payload, repeat=True):
    m.get(f"{BASE}/modbus", payload=["COM1"], repeat=repeat)
    m.get(f"{BASE}/modbus/COM1/all", payload=all_payload, repeat=repeat)
    m.get(f"{BASE}/modbus/COM1/1", payload=controller_payload, repeat=repeat)
    m.get(f"{BASE}/modbus/COM1/1/limits", payload=limits_payload, repeat=repeat)


async def test_get_all(mocked, all_payload, controller_payload, limits_payload):
    _reads(mocked, all_payload, controller_payload, limits_payload)
    async with KE2LDA(IP) as lda:
        ctrls = await lda.get_all()
    assert list(ctrls) == ["COM1-1"]
    assert ctrls["COM1-1"].model == "KE2 Temp"


async def test_write_logs_in_validates_and_sends_cookie(
    mocked, all_payload, controller_payload, limits_payload
):
    _reads(mocked, all_payload, controller_payload, limits_payload)
    mocked.post(f"{BASE}/auth/login", payload=LOGIN_OK)
    mocked.put(f"{BASE}/modbus/COM1/1/Setpoints", payload=WRITE_OK)
    async with KE2LDA(IP) as lda:
        sent = await lda.set_setpoints(1, {"RoomTemperature": "56"})
    assert sent == {"RoomTemperature": 56}
    put = next(v for k, v in mocked.requests.items() if k[0] == "PUT")[0]
    assert put.kwargs["json"] == {"RoomTemperature": 56}
    assert put.kwargs["headers"]["Cookie"] == "modbusSessionID=abc123"
    assert put.kwargs["allow_redirects"] is False


async def test_write_rejected_locally(mocked, all_payload, controller_payload, limits_payload):
    _reads(mocked, all_payload, controller_payload, limits_payload)
    async with KE2LDA(IP) as lda:
        with pytest.raises(KE2ValidationError):
            await lda.set_setpoints(1, {"RoomTemperature": 150})
        with pytest.raises(KE2NotSupportedError):
            await lda.set_setpoints(1, {"NoSuchField": 1})


async def test_write_relogins_once_then_fails(
    mocked, all_payload, controller_payload, limits_payload
):
    _reads(mocked, all_payload, controller_payload, limits_payload)
    mocked.post(f"{BASE}/auth/login", payload=LOGIN_OK, repeat=True)
    mocked.put(f"{BASE}/modbus/COM1/1/Setpoints", status=401, payload={"Message": "Unauthorized"})
    mocked.put(f"{BASE}/modbus/COM1/1/Setpoints", payload=WRITE_OK)
    async with KE2LDA(IP) as lda:
        await lda.set_setpoints(1, {"RoomTemperature": 55}, units="Fahrenheit")
    logins = [k for k in mocked.requests if k[0] == "POST"]
    assert len(mocked.requests[logins[0]]) == 2

    mocked.put(f"{BASE}/modbus/COM1/1/Setpoints", payload={"Message": "Nope"}, repeat=True)
    async with KE2LDA(IP) as lda:
        with pytest.raises(KE2WriteError):
            await lda.set_setpoints(1, {"RoomTemperature": 55}, units="Fahrenheit")


async def test_bad_login(mocked, all_payload, controller_payload, limits_payload):
    _reads(mocked, all_payload, controller_payload, limits_payload)
    mocked.post(
        f"{BASE}/auth/login",
        payload={"status": "failed", "message": "incorrect username or password"},
    )
    async with KE2LDA(IP, password="wrong") as lda:
        with pytest.raises(KE2AuthError):
            await lda.set_setpoints(1, {"RoomTemperature": 55}, units="Fahrenheit")


async def test_redirect_is_an_error(mocked):
    mocked.get(
        f"{BASE}/modbus",
        status=302,
        headers={"Location": "https://ke2lda.ke2.co/modbus"},
    )
    async with KE2LDA(IP) as lda:
        with pytest.raises(KE2ConnectionError, match="addressed by IP"):
            await lda.interfaces()


async def test_missing_category_404(mocked):
    mocked.get(
        f"{BASE}/modbus/COM1/1/limits",
        status=404,
        body=json.dumps(
            {
                "Status": 404,
                "Message": "Device Not Found",
                "Details": "The device requested is not present",
            }
        ),
    )
    async with KE2LDA(IP) as lda:
        with pytest.raises(KE2NotSupportedError):
            await lda.get_schema("COM1", 1)


async def test_hostname_is_resolved_and_sent_as_ip(mocked, monkeypatch):
    lda = KE2LDA("ke2lda.example.lan")

    async def fake_resolve(self=lda):
        self._ip = IP
        return IP

    monkeypatch.setattr(lda, "_resolve_ip", fake_resolve)
    mocked.get(re.compile(rf"^{re.escape(BASE)}/modbus$"), payload=["COM1"])
    assert await lda.interfaces() == ["COM1"]
    req = next(iter(mocked.requests.values()))[0]
    assert req.kwargs["headers"]["Host"] == IP
    await lda.close()
