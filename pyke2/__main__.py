"""Debug CLI: ``python -m pyke2 <ip> status|limits|set|next-mode|info``.

Credentials come from --username/--password or KE2_USERNAME / KE2_PASSWORD
(defaults: the factory ke2admin / ke2admin).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from . import KE2LDA, KE2Error
from .client import DEFAULT_PASSWORD, DEFAULT_USERNAME


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pyke2", description=__doc__)
    p.add_argument("host", help="LDA IP address")
    p.add_argument("--username", default=os.environ.get("KE2_USERNAME", DEFAULT_USERNAME))
    p.add_argument("--password", default=os.environ.get("KE2_PASSWORD", DEFAULT_PASSWORD))
    p.add_argument("--interface", default="COM1")
    p.add_argument("--address", type=int, default=1)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="state of every controller")
    sub.add_parser("limits", help="field schema of one controller")
    sub.add_parser("info", help="LDA version + network info")
    s = sub.add_parser("set", help="write one field")
    s.add_argument("field")
    s.add_argument("value")
    s.add_argument("--category", default="Setpoints")
    sub.add_parser("next-mode", help="advance the operating mode")
    return p


def _coerce(value: str):
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


async def _run(args: argparse.Namespace) -> int:
    async with KE2LDA(args.host, args.username, args.password) as lda:
        if args.cmd == "status":
            for ctrl in (await lda.get_all()).values():
                print(
                    json.dumps(
                        {
                            "key": ctrl.key,
                            "model": ctrl.model,
                            "version": ctrl.version,
                            "room": ctrl.room_temperature,
                            "fault": ctrl.sensor_fault,
                            "setpoint": ctrl.setpoint,
                            "diff": ctrl.differential,
                            "relay_on": ctrl.relay_on,
                            "mode": ctrl.mode,
                            "alarms": ctrl.alarms,
                            "comm_timeouts": ctrl.comm_timeouts,
                        },
                        indent=2,
                    )
                )
        elif args.cmd == "limits":
            schema = await lda.get_schema(args.interface, args.address)
            for spec in schema.fields():
                lo, hi = spec.bounds()
                flag = "rw" if spec.editable else "ro"
                extra = spec.options or (f"{lo}..{hi}" if lo is not None else "")
                print(f"{flag} {spec.category:12} {spec.key:30} {spec.data_type:13} {extra}")
        elif args.cmd == "info":
            print(
                json.dumps(
                    {"version": await lda.version(), "network": await lda.network_info()}, indent=2
                )
            )
        elif args.cmd == "set":
            sent = await lda.set_values(
                args.interface, args.address, args.category, {args.field: _coerce(args.value)}
            )
            ctrl = await lda.get_controller(args.interface, args.address)
            print(f"wrote {sent}; read back {args.field} = {ctrl.value(args.category, args.field)}")
        elif args.cmd == "next-mode":
            print(await lda.next_mode(args.address, interface=args.interface))
    return 0


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except KE2Error as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
