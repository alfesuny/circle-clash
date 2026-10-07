"""Networking/admin tests through FastAPI's TestClient."""

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
        assert hello["map"]["width"] > 0 and len(hello["teams"]) == 3
        a.send_json({"type": "join", "name": "Alice"})
        b.send_json({"type": "join", "name": "Bob"})
        aid = recv_type(a, "welcome")["player_id"]
        recv_type(b, "welcome")
        a.send_json({"type": "team", "team": "red"})
        b.send_json({"type": "team", "team": "blue"})

        # wait until the server state reflects both team choices
        while True:
            s = recv_type(a, "state")
            if {p["team"] for p in s["players"]} == {"red", "blue"}:
                break

        headers = admin_headers(client)
        status = client.get("/api/admin/status", headers=headers).json()
        assert {t["id"]: t["count"] for t in status["teams"]}["red"] == 1

        r = client.post("/api/admin/start", json={"duration": 60}, headers=headers)
        assert r.status_code == 200, r.text

        # late joiners are told to wait
        with client.websocket_connect("/ws") as late:
            late.send_json({"type": "join", "name": "Late"})
            rej = recv_type(late, "join_rejected")
            assert rej["retry"] is True

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
