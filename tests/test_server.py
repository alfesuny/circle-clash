"""Networking/admin tests through FastAPI's TestClient."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import server
from game.config import ADMIN_PASSWORD
from game.game import Game


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "game", Game())
    with TestClient(server.app) as c:
        yield c


def admin_headers(client):
    token = client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).json()["token"]
    return {"X-Admin-Token": token}


def recv_type(ws, kind):
    while True:
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg


def test_pages_served(client):
    assert "LAN SHOOTER" in client.get("/").text
    assert "ADMIN" in client.get("/admin").text
    assert client.get("/static/client.js").status_code == 200


def test_admin_requires_password(client):
    assert client.post("/api/admin/login", json={"password": "nope"}).status_code == 401
    assert client.get("/api/admin/status").status_code == 401
    assert client.post("/api/admin/start", json={"duration": 60}).status_code == 401
    assert client.get("/api/admin/status", headers={"X-Admin-Token": "forged"}).status_code == 401


def test_join_team_start_and_play(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        hello = recv_type(a, "hello")
        assert len(hello["teams"]) == 2
        galadriel = hello["maps"]["Galadriel"]
        assert galadriel["width"] > 0 and galadriel["image_url"] == "/maps/Galadriel/image"
        assert "image_path" not in galadriel
        a.send_json({"type": "join", "name": "Alice"})
        b.send_json({"type": "join", "name": "Bob"})
        aid = recv_type(a, "welcome")["player_id"]
        recv_type(b, "welcome")
        a.send_json({"type": "team", "team": "a"})
        b.send_json({"type": "team", "team": "b"})

        # wait until the server state reflects both team choices
        while True:
            s = recv_type(a, "state")
            if {p["team"] for p in s["players"]} == {"a", "b"}:
                break

        headers = admin_headers(client)
        status = client.get("/api/admin/status", headers=headers).json()
        assert {t["id"]: t["count"] for t in status["teams"]}["a"] == 1

        r = client.post("/api/admin/start", json={"duration": 60}, headers=headers)
        assert r.status_code == 200, r.text

        # late joiners get in and can jump into the running match
        with client.websocket_connect("/ws") as late:
            late.send_json({"type": "join", "name": "Late"})
            lid = recv_type(late, "welcome")["player_id"]
            late.send_json({"type": "team", "team": "b"})
            while True:
                s = recv_type(late, "state")
                row = next((p for p in s["players"] if p["id"] == lid), None)
                if row and row["in_match"] and row["alive"]:
                    break

        a.send_json({"type": "move", "keys": {"w": False, "a": False, "s": True, "d": True}})
        a.send_json({"type": "shoot", "angle": 0.5})
        while True:
            s = recv_type(a, "state")
            me = next(p for p in s["players"] if p["id"] == aid)
            if s["game_state"] == "RUNNING" and me["alive"]:
                break

        assert client.post("/api/admin/end", headers=headers).status_code == 200
        while True:
            s = recv_type(a, "state")
            if s["game_state"] == "ENDED":
                assert s["results"]["teams"]
                break
        assert client.post("/api/admin/lobby", headers=headers).status_code == 200


def test_map_image_and_admin_map_selection(client):
    assert client.get("/maps/Galadriel/image").headers["content-type"] == "image/jpeg"
    assert client.get("/maps/Nope/image").status_code == 404
    assert client.get("/maps/..%2Fserver.py/image").status_code == 404
    assert client.post("/api/admin/map", json={"map_id": "Galadriel"}).status_code == 401
    headers = admin_headers(client)
    status = client.get("/api/admin/status", headers=headers).json()
    assert status["map_id"] == "Galadriel" and status["maps"][0]["id"] == "Galadriel"
    assert client.post("/api/admin/map", json={"map_id": "Nope"}, headers=headers).status_code == 400
    assert client.post("/api/admin/map", json={"map_id": "Galadriel"}, headers=headers).status_code == 200


def test_reconnect_takes_over_stale_socket(client):
    """A browser that reconnects (resume token) while its old socket still looks
    alive gets its player back, and the old socket closing later doesn't
    disconnect it."""
    old = client.websocket_connect("/ws").__enter__()
    old.send_json({"type": "join", "name": "Blip"})
    welcome = recv_type(old, "welcome")
    pid, token = welcome["player_id"], welcome["resume_token"]
    with client.websocket_connect("/ws") as new:
        new.send_json({"type": "join", "name": "Blip", "resume": {"id": pid, "token": token}})
        assert recv_type(new, "welcome")["player_id"] == pid
        try:
            old.__exit__(None, None, None)  # the server already kicked it
        except Exception:
            pass
        for _ in range(5):
            s = recv_type(new, "state")
        assert any(p["id"] == pid for p in s["players"])
        assert server.game.players[pid].connected


class FakeSocket:
    def __init__(self, hang=False):
        self.hang = hang
        self.sent = []

    async def send_text(self, text):
        if self.hang:
            await asyncio.sleep(3600)  # a client whose network stopped draining
        self.sent.append(text)


def test_stalled_client_does_not_block_others(monkeypatch):
    monkeypatch.setattr(server, "SEND_TIMEOUT", 0.2)

    async def scenario():
        conns, handlers = [], []

        async def handler(ws):  # stands in for the per-socket receive loop
            conns.append(server.Conn(ws))
            await asyncio.sleep(3600)

        slow, fast = FakeSocket(hang=True), FakeSocket()
        handlers = [asyncio.create_task(handler(ws)) for ws in (slow, fast)]
        await asyncio.sleep(0)
        clients = server.Clients()
        clients.conns.update(conns)
        t0 = asyncio.get_running_loop().time()
        for i in range(30):
            clients.broadcast_state(f"state-{i}")  # synchronous: can't wait on any socket
            await asyncio.sleep(0.01)
        assert asyncio.get_running_loop().time() - t0 < 1.0
        assert fast.sent[-1] == "state-29"  # the healthy client kept receiving
        await asyncio.sleep(0.4)
        assert handlers[0].cancelled() and conns[0].kicked  # stalled one was dropped
        assert not handlers[1].done()
        handlers[1].cancel()

    asyncio.run(scenario())


def test_browsers_always_revalidate_pages_and_scripts(client):
    """Stale cached scripts from an older version broke joining (page loaded,
    JOIN did nothing). Every page/asset must be revalidated."""
    for path in ("/", "/admin", "/static/client.js", "/static/render.js", "/maps/Galadriel/image"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
        assert r.headers.get("etag"), path  # so unchanged files come back as a cheap 304
