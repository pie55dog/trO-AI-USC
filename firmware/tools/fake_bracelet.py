#!/usr/bin/env python3
"""Pretend to be trO bracelets, for testing the backend and dashboard without hardware.

Speaks exactly what the firmware sends (status, tap with retries, star).
Standard library only.

    export TRO_SERVER=http://localhost:8000          # or https://tro-api.onrender.com
    export TRO_BRACELET_KEY=...                       # BRACELET_API_KEY

    python3 fake_bracelet.py status TRO-1
    python3 fake_bracelet.py tap TRO-1 TRO-2          # both at once, like holding them together
    python3 fake_bracelet.py tap TRO-1 ""             # manual tap from TRO-1 only (button held)
    python3 fake_bracelet.py star TRO-1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

TAP_RETRY_S = 0.3   # firmware: TAP_RETRY_MS
TAP_TIMEOUT_S = 6.0  # firmware: TAP_TIMEOUT_MS


def call(server: str, key: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server.rstrip("/") + path, data=data, method=method)
    req.add_header("X-Bracelet-Key", key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=70) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            return err.code, {}


def tap(server: str, key: str, device: str, peer: str, rssi: int = -32) -> dict:
    """Report a tap like the firmware: retry until paired, refused, or timed out."""
    body = {"device": device, "peer": peer}
    if peer:
        body["rssi"] = rssi
    start = time.monotonic()
    while time.monotonic() - start < TAP_TIMEOUT_S:
        code, resp = call(server, key, "POST", "/bracelets/tap", body)
        if code == 200 and resp.get("status") == "paired":
            return {"device": device, **resp}
        if code != 200:
            return {"device": device, "status": f"http {code}", "detail": resp.get("detail")}
        time.sleep(TAP_RETRY_S)
    return {"device": device, "status": "timed out"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=os.environ.get("TRO_SERVER", "http://localhost:8000"))
    ap.add_argument("--key", default=os.environ.get("TRO_BRACELET_KEY", ""))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("device")
    t = sub.add_parser("tap", help="tap two bracelets together (peer '' = manual tap from one side)")
    t.add_argument("device")
    t.add_argument("peer")
    st = sub.add_parser("star")
    st.add_argument("device")
    args = ap.parse_args()
    if not args.key:
        ap.error("set --key or TRO_BRACELET_KEY")

    if args.cmd == "status":
        print(json.dumps(call(args.server, args.key, "GET", f"/bracelets/{args.device}/status")[1], indent=2))
    elif args.cmd == "star":
        code, resp = call(args.server, args.key, "POST", "/bracelets/star", {"device": args.device})
        print(code, json.dumps(resp))
    elif args.cmd == "tap":
        if not args.peer:  # one bracelet's manual tap
            print(json.dumps(tap(args.server, args.key, args.device, "")))
            return 0
        # Both bracelets notice the touch a moment apart, like real hardware.
        results: list[dict] = []
        threads = [
            threading.Thread(target=lambda: results.append(tap(args.server, args.key, args.device, args.peer))),
            threading.Thread(target=lambda: (time.sleep(0.4), results.append(tap(args.server, args.key, args.peer, args.device)))),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        for r in results:
            print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
