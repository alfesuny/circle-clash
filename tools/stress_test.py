"""Load/robustness test against a running server.

    python tools/stress_test.py --password <admin password> [--bots 11] [--seconds 60]

Simulates a LAN party:
  * N bots join, pick teams, run around (WASD + heartbeat), aim and shoot.
  * One "slow" client stops reading from its socket (like a phone on bad
    Wi-Fi). Before the fix this froze the game for everybody.
  * One "blip" client drops its TCP connection without closing it, then
    reconnects with its resume token while the server still thinks the old
    socket is alive (the ghost/auto-running player bug).
  * One player joins mid-match and jumps into a team; one more tries to join
    when the server is full.
The admin starts the match through the REST API. At the end it prints the
snapshot timing seen by healthy bots and checks the invariants.
"""

import argparse
import asyncio
import json
import math
import random
import statistics
import time
import urllib.request

import websockets


def admin(base: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-Admin-Token": token or ""})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


class Bot:
    def __init__(self, url: str, name: str, team: str | None):
        self.url, self.name, self.team = url, name, team
        self.ws = None
        self.player_id = self.token = None
        self.state_times: list[float] = []
        self.last_state: dict | None = None
        self.rejected: dict | None = None
        self.keys = {"w": False, "a": False, "s": False, "d": False}

    async def connect(self, resume: bool = False, max_queue: int | None = 16):
        self.ws = await websockets.connect(self.url, max_queue=max_queue)
        await self._recv_until("hello")
        msg = {"type": "join", "name": self.name}
        if resume:
            msg["resume"] = {"id": self.player_id, "token": self.token}
        await self.ws.send(json.dumps(msg))
        m = await self._recv_until("welcome", "join_rejected")
        if m["type"] == "join_rejected":
            self.rejected = m
            return False
        self.player_id, self.token = m["player_id"], m["resume_token"]
        if self.team and not resume:
            await self.ws.send(json.dumps({"type": "team", "team": self.team}))
        if max_queue != 1:  # keep reading, like a browser does (the slow client doesn't)
            self.reader_task = asyncio.create_task(self.reader())
        return True

    async def _recv_until(self, *kinds):
        while True:
            m = json.loads(await self.ws.recv())
            if m["type"] in kinds:
                return m

    def me(self) -> dict | None:
        if not self.last_state:
            return None
        return next((p for p in self.last_state["players"] if p["id"] == self.player_id), None)

    async def reader(self):
        try:
            async for text in self.ws:
                m = json.loads(text)
                if m["type"] == "state":
                    self.state_times.append(time.monotonic())
                    self.last_state = m
        except websockets.ConnectionClosed:
            pass

    async def play(self, until: float):
        """Wander toward the middle of the map with a 250 ms key heartbeat,
        aiming and shooting at the nearest visible enemy."""
        next_change = 0.0
        try:
            while time.monotonic() < until:
                now = time.monotonic()
                me = self.me()
                if now >= next_change:
                    self.keys = {k: random.random() < 0.3 for k in self.keys}
                    if me and me.get("x") is not None and random.random() < 0.6:
                        # head for the centre (800, 450) so teams actually meet
                        self.keys.update({"a": me["x"] > 800, "d": me["x"] < 800,
                                          "w": me["y"] > 450, "s": me["y"] < 450})
                    next_change = now + random.uniform(0.5, 1.5)
                await self.ws.send(json.dumps({"type": "move", "keys": self.keys}))
                angle = random.uniform(-3.14, 3.14)
                enemies = [p for p in (self.last_state or {}).get("players", [])
                           if me and p.get("alive") and p.get("x") is not None and p["team"] != me["team"]]
                if me and me.get("x") is not None and enemies:
                    e = min(enemies, key=lambda p: math.hypot(p["x"] - me["x"], p["y"] - me["y"]))
                    angle = math.atan2(e["y"] - me["y"], e["x"] - me["x"])
                await self.ws.send(json.dumps({"type": "aim", "angle": angle}))
                await self.ws.send(json.dumps({"type": "shoot", "angle": angle}))
                await asyncio.sleep(0.25)
        except websockets.ConnectionClosed:
            pass


def gaps_ms(times: list[float]) -> list[float]:
    return [(b - a) * 1000 for a, b in zip(times, times[1:])]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:8000")
    ap.add_argument("--password", required=True)
    ap.add_argument("--bots", type=int, default=11)
    ap.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args()
    url, base = f"ws://{args.host}/ws", f"http://{args.host}"
    token = admin(base, "/api/admin/login", body={"password": args.password})["token"]
    teams = [t["id"] for t in admin(base, "/api/admin/status", token)["teams"]]

    bots = [Bot(url, f"bot{i}", teams[i % len(teams)]) for i in range(args.bots)]
    for b in bots:
        assert await b.connect(), b.rejected
    slow = Bot(url, "slowpoke", teams[0])
    assert await slow.connect(max_queue=1)  # tiny queue: stops reading from TCP almost at once
    blip = Bot(url, "blip", teams[1])
    assert await blip.connect()
    await asyncio.sleep(1)

    admin(base, "/api/admin/start", token, {"duration": int(args.seconds) + 30})
    print(f"Match started with {args.bots} bots + slow + blip client")
    t0 = time.monotonic()
    until = t0 + args.seconds
    players = [asyncio.create_task(b.play(until)) for b in bots]

    # Slow client: joins the action, then never reads again.
    await slow.ws.send(json.dumps({"type": "move", "keys": {"d": True}}))

    # Blip: after a few seconds, kill the TCP connection without a close frame
    # and reconnect while the server still has the old socket.
    await asyncio.sleep(min(5, args.seconds / 4))
    await blip.ws.send(json.dumps({"type": "move", "keys": {"d": True}}))
    blip.ws.transport.abort()
    old_id = blip.player_id
    assert await blip.connect(resume=True), blip.rejected
    assert blip.player_id == old_id, "blip client did not get its player back"
    print("Blip client reconnected and took over its player")

    # Mid-match joiner.
    late = Bot(url, "latecomer", teams[1])
    assert await late.connect(), late.rejected

    # The slow client stopped reading; the server must drop it (send timeout or
    # ping timeout, whichever fires first) while everyone else keeps playing.
    slow_dropped = False
    for _ in range(30):
        await asyncio.sleep(1)
        slow_dropped = not any(p["name"] == "slowpoke" and p["connected"]
                               for p in admin(base, "/api/admin/status", token)["players"])
        if slow_dropped:
            break
    print(f"Slow client dropped by the server: {slow_dropped}")

    # Fill the server; the next join must be refused as full.
    fillers, full = [], False
    for i in range(20):
        f = Bot(url, f"filler{i}", None)
        if not await f.connect():
            full = "full" in f.rejected["reason"]
            break
        fillers.append(f)
    connected = sum(p["connected"] for p in admin(base, "/api/admin/status", token)["players"])
    print(f"Server filled to {connected} players; next join rejected as full: {full}")

    await asyncio.gather(*players)
    status = admin(base, "/api/admin/status", token)
    admin(base, "/api/admin/end", token, {})

    # ---------------------------------------------------------------- report
    window = [t for t in bots[0].state_times if t0 <= t <= until]
    deaths = sum(p["deaths"] for p in status["players"])
    all_gaps = [g for b in bots for g in gaps_ms([t for t in b.state_times if t0 <= t <= until])]
    print(f"\nSnapshots seen by bot0 during the match: {len(window)} in {args.seconds:.0f}s "
          f"({len(window) / args.seconds:.1f}/s)")
    print(f"Inter-snapshot gap over all healthy bots: median {statistics.median(all_gaps):.1f} ms, "
          f"p99 {sorted(all_gaps)[int(len(all_gaps) * 0.99)]:.1f} ms, max {max(all_gaps):.1f} ms")
    names = [p["name"] for p in status["players"] if p["connected"]]
    late_row = late.me()
    checks = {
        "no snapshot gap > 250 ms (no freeze)": max(all_gaps) < 250,
        "blip player exists exactly once": names.count("blip") == 1,
        "latecomer is in the match": bool(late_row and late_row["in_match"]),
        "slow client dropped, others unaffected": slow_dropped,
        "server-full join rejected at 14": full and connected == 14,
        f"kills happened ({deaths} deaths)": deaths > 0,
    }
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    for b in bots + [slow, blip, late] + fillers:
        try:
            await b.ws.close()
        except Exception:
            pass
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    asyncio.run(main())
