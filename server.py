"""LAN Shooter server: HTTP routes, WebSocket networking, admin API and the game loop.

Run with:   python server.py
       or:  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import logging
import secrets
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game.config import ADMIN_PASSWORD, GAME_CONFIG, MAP, TEAMS
from game.game import RUNNING, Game, GameError

log = logging.getLogger("lanshooter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

STATIC = Path(__file__).parent / "static"
game = Game()

# Config the client needs for rendering/prediction (sent once on connect).
CLIENT_CONFIG = {k: GAME_CONFIG[k] for k in (
    "player_radius", "player_health", "fire_cooldown", "tick_rate",
    "max_players_per_team", "max_name_length")}


# --------------------------------------------------------------------- clients
class Clients:
    """Open game WebSockets and which player (if any) each one controls."""

    def __init__(self):
        self.sockets: dict[WebSocket, str | None] = {}

    async def broadcast(self, text: str) -> None:
        # Send failures are ignored here: the socket's receive loop notices the
        # disconnect and cleans up (including removing the player).
        await asyncio.gather(*(ws.send_text(text) for ws in list(self.sockets)), return_exceptions=True)


clients = Clients()


async def game_loop() -> None:
    """Fixed-rate tick: simulate, then broadcast one shared snapshot."""
    interval = 1.0 / GAME_CONFIG["tick_rate"]
    last = time.monotonic()
    while True:
        now = time.monotonic()
        try:
            game.tick(min(now - last, 0.1), now)  # cap dt so a stall can't teleport players
            if clients.sockets:
                await clients.broadcast(json.dumps(game.snapshot(now), separators=(",", ":")))
        except Exception:
            log.exception("Error in game loop")
        last = now
        await asyncio.sleep(max(0.0, interval - (time.monotonic() - now)))


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
    task = asyncio.create_task(game_loop())
    print("\n" + "=" * 56)
    print("  LAN SHOOTER is running")
    for ip in lan_addresses() or ["<your-local-ip>"]:
        print(f"  Players join at:  http://{ip}:8000")
    print("  Admin panel:      http://localhost:8000/admin")
    print(f"  Admin password:   {ADMIN_PASSWORD}")
    print("=" * 56 + "\n", flush=True)
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
async def admin_page():
    return FileResponse(STATIC / "admin.html")


# ------------------------------------------------------------- game websocket
async def send(ws: WebSocket, msg: dict) -> None:
    await ws.send_text(json.dumps(msg))


async def handle_message(ws: WebSocket, msg: dict) -> None:
    """Dispatch one client->server message. Clients only ever send input."""
    kind = msg.get("type")
    pid = clients.sockets.get(ws)

    if kind == "join":
        if pid is not None:
            return
        player = None
        resume = msg.get("resume")
        if isinstance(resume, dict):
            try:
                player = game.resume(str(resume.get("id")), str(resume.get("token")))
                log.info("Player %s (%s) reconnected", player.name, player.id)
            except GameError:
                player = None
        if player is None:
            try:
                player = game.join(msg.get("name"))
            except GameError as e:
                # retry=True: the client waits and re-joins automatically once
                # the match ends / a slot frees up.
                retry = game.state == RUNNING or "full" in str(e)
                await send(ws, {"type": "join_rejected", "reason": str(e), "retry": retry})
                return
            log.info("Player %s (%s) connected", player.name, player.id)
        clients.sockets[ws] = player.id
        await send(ws, {"type": "welcome", "player_id": player.id, "name": player.name,
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
        await send(ws, {"type": "error", "message": str(e)})


@app.websocket("/ws")
async def game_socket(ws: WebSocket):
    await ws.accept()
    clients.sockets[ws] = None
    await send(ws, {"type": "hello", "config": CLIENT_CONFIG, "map": MAP, "teams": TEAMS})
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
                await handle_message(ws, msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket error")
    finally:
        pid = clients.sockets.pop(ws, None)
        if pid is not None:
            player = game.players.get(pid)
            log.info("Player %s (%s) disconnected", player.name if player else "?", pid)
            game.disconnect(pid)


# ------------------------------------------------------------------ admin api
admin_tokens: set[str] = set()


def require_admin(token: str | None) -> None:
    if not token or token not in admin_tokens:
        raise HTTPException(status_code=401, detail="Not logged in as admin.")


class LoginBody(BaseModel):
    password: str


class StartBody(BaseModel):
    duration: int | None = None


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
    log.info("Admin started a %ss match", game.duration)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
