"""Async client for the KE2 LDA (Local Area Dashboard and Alarms) JSON API.

Reads need no auth. Writes need a ``modbus`` session, sent as the ``modbusSessionID``
cookie. The LDA's nginx 302-redirects any request whose Host header isn't its IP to
KE2's cloud, so the client always sends ``Host: <ip>`` and never follows redirects.
See ``research/01-http-api-reference.md``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import aiohttp

from .exceptions import (
    KE2AuthError,
    KE2ConnectionError,
    KE2NotSupportedError,
    KE2WriteError,
)
from .models import MANUAL_CONTROL, SETPOINTS, Controller
from .schema import Schema

_LOGGER = logging.getLogger(__name__)

DEFAULT_USERNAME = "ke2admin"
DEFAULT_PASSWORD = "ke2admin"
DEFAULT_TIMEOUT = 15.0
SESSION_COOKIE = "modbusSessionID"


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class KE2LDA:
    """A KE2 LDA and the controllers on its Modbus interfaces."""

    def __init__(
        self,
        host: str,
        username: str = DEFAULT_USERNAME,
        password: str = DEFAULT_PASSWORD,
        *,
        session: aiohttp.ClientSession | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        port: int = 80,
    ) -> None:
        self.host = host.strip().removeprefix("http://").rstrip("/")
        self.port = port
        self._username = username
        self._password = password
        self._session = session
        self._own_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session_id: str | None = None
        self._ip: str | None = self.host if _is_ip(self.host) else None
        self._schemas: dict[str, Schema] = {}
        self._login_lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────
    async def __aenter__(self) -> KE2LDA:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def _resolve_ip(self) -> str:
        """The LDA only answers to its IP in the Host header; resolve a hostname once."""
        if self._ip is None:
            loop = asyncio.get_running_loop()
            try:
                infos = await loop.getaddrinfo(self.host, self.port, family=socket.AF_INET)
            except OSError as err:
                raise KE2ConnectionError(f"cannot resolve {self.host}: {err}") from err
            self._ip = infos[0][4][0]
        return self._ip

    # ── transport ────────────────────────────────────────────────────────
    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        auth: bool = False,
    ) -> Any:
        ip = await self._resolve_ip()
        url = f"http://{ip}:{self.port}{path}" if self.port != 80 else f"http://{ip}{path}"
        headers = {"Host": ip, "Accept": "application/json"}
        if auth and self._session_id:
            headers["Cookie"] = f"{SESSION_COOKIE}={self._session_id}"
        try:
            async with self._http().request(
                method,
                url,
                json=payload,
                headers=headers,
                allow_redirects=False,
                timeout=self._timeout,
            ) as resp:
                text = await resp.text()
                status = resp.status
                location = resp.headers.get("Location")
        except (TimeoutError, aiohttp.ClientError) as err:
            raise KE2ConnectionError(f"{method} {path}: {err or type(err).__name__}") from err

        if 300 <= status < 400:
            raise KE2ConnectionError(
                f"{method} {path}: redirected to {location!r} (the LDA must be addressed by IP)"
            )
        try:
            body = json.loads(text) if text.strip() else None
        except json.JSONDecodeError as err:
            raise KE2ConnectionError(f"{method} {path}: HTTP {status}, non-JSON reply") from err
        if status == 404 and isinstance(body, Mapping):
            raise KE2NotSupportedError(f"{path}: {body.get('Details') or body.get('Message')}")
        if status >= 400 and not auth:
            raise KE2ConnectionError(f"{method} {path}: HTTP {status}")
        return body

    # ── auth ─────────────────────────────────────────────────────────────
    async def login(self) -> None:
        async with self._login_lock:
            body = await self._request(
                "POST",
                "/auth/login",
                payload={
                    "action": "login",
                    "role": "modbus",
                    "username": self._username,
                    "password": self._password,
                },
            )
            if not isinstance(body, Mapping) or body.get("status") != "success":
                self._session_id = None
                msg = body.get("message") if isinstance(body, Mapping) else body
                raise KE2AuthError(f"login failed: {msg}")
            self._session_id = str(body["sessionID"])

    async def logout(self) -> None:
        if self._session_id:
            try:
                await self._request(
                    "POST",
                    "/auth/logout",
                    payload={"action": "logout", "sessionID": self._session_id},
                )
            finally:
                self._session_id = None

    # ── discovery / reads ────────────────────────────────────────────────
    async def interfaces(self) -> list[str]:
        body = await self._request("GET", "/modbus")
        return [str(i) for i in body or []]

    async def version(self) -> dict[str, Any]:
        return await self._request("GET", "/version.json") or {}

    async def network_info(self) -> dict[str, Any]:
        return await self._request("GET", "/smartaccess/client/exec/networkInfo.lua") or {}

    async def get_all(self) -> dict[str, Controller]:
        """Every controller on every interface, keyed by ``Controller.key``."""
        result: dict[str, Controller] = {}
        for iface in await self.interfaces():
            body = await self._request("GET", f"/modbus/{quote(iface)}/all")
            for item in body or []:
                if not isinstance(item, Mapping):
                    continue
                ctrl = Controller.from_api(iface, item)
                ctrl.schema = self._schemas.get(ctrl.key)
                result[ctrl.key] = ctrl
        return result

    async def get_controller(self, interface: str, address: int) -> Controller:
        body = await self._request("GET", f"/modbus/{quote(interface)}/{address}")
        ctrl = Controller.from_api(interface, body or {})
        ctrl.schema = self._schemas.get(ctrl.key)
        return ctrl

    async def get_schema(self, interface: str, address: int, *, refresh: bool = False) -> Schema:
        """The controller's field schema (cached; it only changes with firmware)."""
        key = f"{interface}-{address}"
        if refresh or key not in self._schemas:
            body = await self._request("GET", f"/modbus/{quote(interface)}/{address}/limits")
            self._schemas[key] = Schema.from_limits(body or {})
        return self._schemas[key]

    # ── writes ───────────────────────────────────────────────────────────
    async def _put(self, path: str, values: Mapping[str, Any]) -> None:
        for attempt in (1, 2):
            if self._session_id is None:
                await self.login()
            body = await self._request("PUT", path, payload=dict(values), auth=True)
            if isinstance(body, Mapping) and body.get("Message") == "Success":
                return
            if attempt == 1:
                # Most likely an expired session: log in again and retry once.
                _LOGGER.debug("KE2 write to %s not confirmed (%s); re-login", path, body)
                self._session_id = None
                continue
            raise KE2WriteError(f"PUT {path} {dict(values)} → {body}")

    async def set_values(
        self,
        interface: str,
        address: int,
        category: str,
        values: Mapping[str, Any],
        *,
        units: str | None = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Validate against the schema, write ``values`` to ``category``; return what was sent."""
        sent = dict(values)
        if validate:
            schema = await self.get_schema(interface, address)
            if units is None:
                ctrl = await self.get_controller(interface, address)
                units = ctrl.units
            sent = {k: schema.require(category, k).validate(v, units) for k, v in values.items()}
        await self._put(f"/modbus/{quote(interface)}/{address}/{quote(category)}", sent)
        return sent

    async def set_setpoints(
        self,
        address: int,
        values: Mapping[str, Any],
        *,
        interface: str = "COM1",
        units: str | None = None,
    ) -> dict[str, Any]:
        return await self.set_values(interface, address, SETPOINTS, values, units=units)

    async def set_system_on(self, address: int, on: bool, *, interface: str = "COM1") -> None:
        """Manual Control on/off (only on models that have it)."""
        schema = await self.get_schema(interface, address)
        if (MANUAL_CONTROL, "System Off") not in schema:
            raise KE2NotSupportedError("this controller has no Manual Control")
        await self._put(
            f"/modbus/{quote(interface)}/{address}/{quote(MANUAL_CONTROL)}",
            {"System Off": "System On" if on else "Modbus Off"},
        )

    async def next_mode(self, address: int, *, interface: str = "COM1") -> Any:
        """Advance the operating mode (the web UI's 'Next Mode' button)."""
        if self._session_id is None:
            await self.login()
        return await self._request(
            "POST", f"/modbus/{quote(interface)}/{address}/GotoNextMode", auth=True
        )
