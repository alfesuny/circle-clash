"""LAN Shooter server: HTTP routes, WebSocket networking, admin API and the game loop.

Run with:   python server.py
       or:  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import logging
import queue
import secrets
import socket
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game.config import ADMIN_PASSWORD, GAME_CONFIG
from game.game import Game, GameError

log = logging.getLogger("lanshooter")

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
LOG_FILE = ROOT / "server.log"
game = Game()

# Config the client needs for rendering/prediction (sent once on connect).
CLIENT_CONFIG = {k: GAME_CONFIG[k] for k in (
    "player_radius", "player_health", "fire_cooldown", "tick_rate",
    "max_players_per_team", "max_name_length")}

SEND_TIMEOUT = 5.0     # a socket that can't take a message for this long is dropped
STALL_WARNING = 0.25   # log when a game-loop iteration is this late (seconds)


# --------------------------------------------------------------------- logging
_log_listener: QueueListener | None = None


def setup_logging(to_file: bool) -> None:
    """Log through a queue so console/file writes happen on a background
    thread. A blocked console (e.g. Windows QuickEdit selection) then can't
    freeze the game loop."""
    global _log_listener
    if _log_listener is not None:
        return
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
    q: queue.SimpleQueue = queue.SimpleQueue()
    _log_listener = QueueListener(q, *handlers, respect_handler_level=True)
    _log_listener.start()
    log.addHandler(QueueHandler(q))
    log.setLevel(logging.INFO)
    log.propagate = False


def disable_console_quickedit() -> None:
    """On Windows, clicking in the console window starts a text selection that
    pauses every write to it, which used to freeze the whole server. Turn
    QuickEdit off for this console."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
            kernel32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
    except Exception:  # not a real console (IDE, pipe): nothing to do
        pass


# --------------------------------------------------------------------- clients
class Conn:
    """One game WebSocket and the player (if any) it controls.

    Outgoing messages go through a per-connection sender task so the game loop
    never waits on a socket: a slow client only delays itself. Control
    messages (welcome, errors) are queued in order; game states are not -
    only the newest one is kept, so a client that falls behind skips frames
    instead of building a backlog.
    """

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.player_id: str | None = None
        self._outbox: deque[str] = deque()
        self._latest_state: str | None = None
        self._wake = asyncio.Event()
        self._handler = asyncio.current_task()  # the receive loop, cancelled on kick()
        self.kicked = False
        self._sender = asyncio.create_task(self._send_loop())

    def push(self, msg: dict) -> None:
        self._outbox.append(json.dumps(msg, separators=(",", ":")))
        self._wake.set()

    def push_state(self, text: str) -> None:
        self._latest_state = text
        self._wake.set()

    async def _send_loop(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._outbox or self._latest_state is not None:
                    if self._outbox:
                        text = self._outbox.popleft()
                    else:
                        text, self._latest_state = self._latest_state, None
                    await asyncio.wait_for(self.ws.send_text(text), SEND_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            log.warning("Dropping %s: it stopped accepting data", self.describe())
            self.kick()
        except Exception:
            self.kick()  # socket closed underneath us; the receive loop cleans up

    def describe(self) -> str:
        p = game.players.get(self.player_id) if self.player_id else None
        return f"player {p.name} ({p.id})" if p else "an unjoined socket"

    def kick(self) -> None:
        """Stop this connection now (stalled or replaced by a reconnect)."""
        if self.kicked:
            return
        self.kicked = True
        self._sender.cancel()
        if self._handler is not None:
            self._handler.cancel()

    def stop(self) -> None:
        self._sender.cancel()


class Clients:
    def __init__(self):
        self.conns: set[Conn] = set()

    def broadcast_state(self, text: str) -> None:
        for c in self.conns:
            c.push_state(text)

    def owning(self, player_id: str) -> list[Conn]:
        return [c for c in self.conns if c.player_id == player_id]


clients = Clients()


async def game_loop() -> None:
    """Fixed-rate tick: simulate, then hand one shared snapshot to every client.
    Nothing in here awaits a socket, so no client can stall the game."""
    interval = 1.0 / GAME_CONFIG["tick_rate"]
    last = time.monotonic()
    deadline = last
    while True:
        now = time.monotonic()
        if now - last > interval + STALL_WARNING:
            log.warning("Game loop stalled for %.0f ms", (now - last - interval) * 1000)
        try:
            game.tick(min(now - last, 0.1), now)  # cap dt so a stall can't teleport players
            if clients.conns:
                clients.broadcast_state(json.dumps(game.snapshot(now), separators=(",", ":")))
        except Exception:
            log.exception("Error in game loop")
        last = now
        # Sleep until an absolute deadline: timer granularity (~16 ms on
        # Windows) then averages out instead of slowing every tick down.
        deadline = max(deadline + interval, time.monotonic())
        await asyncio.sleep(deadline - time.monotonic())


def lan_addresses() -> list[str]:
    addrs = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packets are sent; picks the LAN interface
            addrs.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging(to_file=False)  # no-op if __main__ already set it up (with a file)
    task = asyncio.create_task(game_loop())
    print("\n" + "=" * 56)
    print("  LAN SHOOTER is running")
    for ip in lan_addresses() or ["<your-local-ip>"]:
        print(f"  Players join at:  http://{ip}:8000")
    print("  Admin panel:      http://localhost:8000/admin")
    print(f"  Admin password:   {ADMIN_PASSWORD}")
    print(f"  Maps:             {', '.join(game.maps)}")
    print("=" * 56 + "\n", flush=True)
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def always_revalidate(request, call_next):
    """Make browsers check for a newer version of every page/script/image.
    Without this they may reuse files cached from an older version of the
    game for hours, and old scripts break against the new server (the page
    loads but JOIN silently fails). Unchanged files still come back as a
    cheap 304 thanks to their ETag."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
async def admin_page():
    return FileResponse(STATIC / "admin.html")


def map_image_url(map_id: str) -> str:
    return f"/maps/{map_id}/image"


def public_map(m: dict) -> dict:
    """Map data for clients (world coordinates, no server paths)."""
    return {"id": m["id"], "name": m["name"], "width": m["width"], "height": m["height"],
            "walls": m["walls"], "spawn_zones": m["spawn_zones"], "image_url": map_image_url(m["id"])}


@app.get("/maps/{map_id}/image")
async def map_image(map_id: str):
    # Only images of loaded maps are served (never an arbitrary path).
    m = game.maps.get(map_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Unknown map.")
    return FileResponse(m["image_path"])


# ------------------------------------------------------------- game websocket
def handle_message(conn: Conn, msg: dict) -> None:
    """Dispatch one client->server message. Clients only ever send input."""
    kind = msg.get("type")
    pid = conn.player_id

    if kind == "join":
        if pid is not None:
            return
        player = None
        resume = msg.get("resume")
        if isinstance(resume, dict):
            try:
                player = game.resume(str(resume.get("id")), str(resume.get("token")))
                # A reconnect after a network blip: the old socket may still
                # look alive. Detach it so its cleanup can't disconnect us.
                for old in clients.owning(player.id):
                    old.player_id = None
                    old.kick()
                log.info("Player %s (%s) reconnected", player.name, player.id)
            except GameError:
                player = None
        if player is None:
            try:
                player = game.join(msg.get("name"))
            except GameError as e:
                # retry=True: the client waits and re-joins automatically once a slot frees up.
                conn.push({"type": "join_rejected", "reason": str(e), "retry": "full" in str(e)})
                return
            log.info("Player %s (%s) connected", player.name, player.id)
        conn.player_id = player.id
        conn.push({"type": "welcome", "player_id": player.id, "name": player.name,
                   "resume_token": player.resume_token})
        return

    if pid is None:
        return  # ignore input from sockets that haven't joined
    try:
        if kind == "team":
            game.choose_team(pid, msg.get("team"))
        elif kind == "move":
            game.set_keys(pid, msg.get("keys"))
        elif kind == "aim":
            game.set_aim(pid, msg.get("angle"))
        elif kind == "shoot":
            game.shoot(pid, msg.get("angle"))
    except GameError as e:
        conn.push({"type": "error", "message": str(e)})


@app.websocket("/ws")
async def game_socket(ws: WebSocket):
    await ws.accept()
    conn = Conn(ws)
    clients.conns.add(conn)
    conn.push({"type": "hello", "config": CLIENT_CONFIG, "teams": game.teams,
               "maps": {mid: public_map(m) for mid, m in game.maps.items()}})
    try:
        while True:
            text = await ws.receive_text()
            if len(text) > 2000:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if isinstance(msg, dict):
                handle_message(conn, msg)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        if not conn.kicked:
            raise  # server shutdown, not our own kick()
        task = asyncio.current_task()
        if task is not None and hasattr(task, "uncancel"):
            task.uncancel()  # we handled our own kick; let the cleanup below await normally
    except Exception:
        log.exception("WebSocket error")
    finally:
        clients.conns.discard(conn)
        conn.stop()
        pid = conn.player_id
        if pid is not None and not clients.owning(pid):
            player = game.players.get(pid)
            log.info("Player %s (%s) disconnected", player.name if player else "?", pid)
            game.disconnect(pid)
        if conn.kicked:
            try:
                await asyncio.wait_for(ws.close(), 1.0)
            except Exception:
                pass


# ------------------------------------------------------------------ admin api
admin_tokens: set[str] = set()


def require_admin(token: str | None) -> None:
    if not token or token not in admin_tokens:
        raise HTTPException(status_code=401, detail="Not logged in as admin.")


class LoginBody(BaseModel):
    password: str


class StartBody(BaseModel):
    duration: int | None = None


class MapBody(BaseModel):
    map_id: str


@app.post("/api/admin/login")
async def admin_login(body: LoginBody):
    if not secrets.compare_digest(body.password.encode(), ADMIN_PASSWORD.encode()):
        raise HTTPException(status_code=401, detail="Wrong password.")
    token = secrets.token_urlsafe(24)
    admin_tokens.add(token)
    return {"token": token}


@app.get("/api/admin/status")
async def admin_status(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    snap = game.snapshot()
    snap["players"] = [{
        "id": p.id, "name": p.name, "team": p.team, "connected": p.connected,
        "in_match": p.in_match, "kills": p.kills, "deaths": p.deaths, "score": game.score(p),
    } for p in game.players.values()]
    snap["config"] = {k: GAME_CONFIG[k] for k in ("min_game_duration", "max_game_duration", "max_players_per_team")}
    snap["maps"] = [{"id": m["id"], "name": m["name"], "image_url": map_image_url(m["id"])} for m in game.maps.values()]
    snap.pop("bullets")
    return snap


async def admin_action(token: str | None, action) -> dict:
    require_admin(token)
    try:
        action()
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "game_state": game.state}


@app.post("/api/admin/start")
async def admin_start(body: StartBody, x_admin_token: str | None = Header(default=None)):
    result = await admin_action(x_admin_token, lambda: game.start(body.duration))
    log.info("Admin started a %ss match on %s", game.duration, game.map_id)
    return result


@app.post("/api/admin/end")
async def admin_end(x_admin_token: str | None = Header(default=None)):
    return await admin_action(x_admin_token, game.end)


@app.post("/api/admin/lobby")
async def admin_lobby(x_admin_token: str | None = Header(default=None)):
    return await admin_action(x_admin_token, game.back_to_lobby)


@app.post("/api/admin/duration")
async def admin_duration(body: StartBody, x_admin_token: str | None = Header(default=None)):
    return await admin_action(x_admin_token, lambda: game.set_duration(body.duration))


@app.post("/api/admin/map")
async def admin_map(body: MapBody, x_admin_token: str | None = Header(default=None)):
    return await admin_action(x_admin_token, lambda: game.set_map(body.map_id))


if __name__ == "__main__":
    import uvicorn

    disable_console_quickedit()
    setup_logging(to_file=True)
    # Pings detect vanished clients (closed laptop, dropped Wi-Fi) within seconds.
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning",
                ws_ping_interval=5, ws_ping_timeout=10)
