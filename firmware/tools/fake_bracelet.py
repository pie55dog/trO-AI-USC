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

    # Mic build: send a recording exactly like a bracelet does (raw WAV body).
    # connection_id is the "connection_id" printed by `tap`.
    python3 fake_bracelet.py record TRO-1 conversation.wav --connection 12
    python3 fake_bracelet.py record TRO-1 note.wav --voice-note

Any WAV works for testing (record one on a laptop or phone). For the best
"who said what", record the same conversation on two devices, one near each
person, and send each file from that person's bracelet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
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


def upload(server: str, key: str, device: str, path: str, connection: int | None, started_at: int | None) -> tuple[int, dict]:
    """POST /bracelets/recordings with the file as the raw body, like the firmware."""
    params = {"device": device, "kind": "conversation" if connection else "voice_note"}
    if connection:
        params["connection_id"] = str(connection)
    if started_at:
        params["started_at"] = str(started_at)
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(
        server.rstrip("/") + "/bracelets/recordings?" + urllib.parse.urlencode(params), data=data, method="POST"
    )
    req.add_header("X-Bracelet-Key", key)
    req.add_header("Content-Type", "audio/wav" if path.lower().endswith(".wav") else "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
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
    rec = sub.add_parser("record", help="upload a recording (mic build)")
    rec.add_argument("device")
    rec.add_argument("file", help="audio file, ideally 16 kHz mono WAV")
    group = rec.add_mutually_exclusive_group(required=True)
    group.add_argument("--connection", type=int, help="connection_id from the tap (a conversation)")
    group.add_argument("--voice-note", action="store_true")
    rec.add_argument("--started-at", type=int, help="Unix ms when recording started (default: now)")
    args = ap.parse_args()
    if not args.key:
        ap.error("set --key or TRO_BRACELET_KEY")

    if args.cmd == "status":
        print(json.dumps(call(args.server, args.key, "GET", f"/bracelets/{args.device}/status")[1], indent=2))
    elif args.cmd == "record":
        started = args.started_at or int(time.time() * 1000)
        code, resp = upload(args.server, args.key, args.device, args.file, args.connection, started)
        print(code, json.dumps(resp))
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
