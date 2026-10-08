# Circle Clash

**A LAN party shooter for the browser.** A small top-down, team-based multiplayer shooter for your local network.
One computer runs the server; everyone else on the same Wi-Fi/LAN joins from a browser — no installs.

## Setup (host computer, once)

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## Running the server

```bash
python server.py
```

or equivalently:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

The server binds to `0.0.0.0` so other devices can reach it. On startup it prints:

```
  Players join at:  http://192.168.x.x:8000
  Admin panel:      http://localhost:8000/admin
  Admin password:   3fa9c2
```

- **Players** open `http://<host-ip>:8000` in a browser, enter a name and pick a team.
- **Admin** (you) opens `/admin`, logs in with the printed password, sets the match duration and clicks **START GAME**.

The admin password is random each run unless you set one:

```bash
# Windows PowerShell
$env:LAN_SHOOTER_ADMIN_PASSWORD = "mypassword"; python server.py
# macOS/Linux
LAN_SHOOTER_ADMIN_PASSWORD=mypassword python server.py
```

### Finding your local IP

The server prints it, but you can also check manually:
- Windows: `ipconfig` → "IPv4 Address" of your Wi-Fi/Ethernet adapter
- macOS: `ipconfig getifaddr en0`
- Linux: `hostname -I`

### Firewall

If other devices can't connect, your firewall is probably blocking it.
On Windows, allow Python when the "Windows Defender Firewall" prompt appears (tick **Private networks**),
or add an inbound rule for TCP port 8000. Make sure your network is set to *Private*, not *Public*.

## Controls

| Action | Input |
| --- | --- |
| Move | W A S D (or arrow keys) |
| Aim | Mouse |
| Shoot | Left click (hold to keep firing) |

A keyboard and mouse are required; there are no touch controls yet.

## Rules

- 3 teams (RED, GREEN, BLUE), max 5 players each. Team changes are allowed until the match starts.
- 4 HP; each enemy hit removes 1. No friendly fire. Walls block bullets and movement.
- Respawn 3 s after death in your team's spawn zone, with 3 s of invulnerability (flashing).
- You can't be damaged while inside your own team's spawn zone (shield ring) — but bullets fired from inside your spawn
  stop at its edge, so to shoot anyone you have to step out and expose yourself.
- You can't walk into another team's spawn zone.
- Kill = 10 points. Team score = total kills by its members. Highest team score wins when the timer hits zero.
- Players who arrive while a match is running wait and join automatically when it ends.
- Refreshing the browser during a match reconnects you to your player (same team and stats).

## Configuration

All tuning values (health, speeds, cooldown, respawn delay, team size, tick rate, …),
the team list, and the map (walls and spawn zones) are in [game/config.py](game/config.py).
To add a team, add an entry to `TEAMS` and a matching spawn zone in `MAP["spawn_zones"]`.

## Tests

```bash
python -m pytest            # all tests
python -m pytest tests/test_game.py::test_walls_block_bullets   # a single test
```

## Project layout

```
server.py            HTTP routes, WebSocket networking, admin API, fixed-rate game loop
game/config.py       GAME_CONFIG, TEAMS, MAP
game/game.py         authoritative game state and rules (no I/O)
game/collision.py    geometry helpers
game/entities.py     Player / Bullet data
static/              browser client (index.html, client.js, render.js) and admin page
tests/               pytest suite
```
