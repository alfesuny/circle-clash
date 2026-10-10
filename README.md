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
- **Admin** (you) opens `/admin`, logs in with the printed password, picks the map, sets the match duration and clicks **START GAME**.

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

- 2 teams (TEAM A, TEAM B), max 7 players each (14 total). Team changes are allowed until the match starts.
- 4 lives (hearts); each enemy hit removes one. No friendly fire. Walls block bullets and movement.
- One shot every 0.5 s (hold the mouse button to keep firing).
- Players are drawn as standing soldiers that face and aim toward the mouse and walk when moving.
  Bullets hit a capsule from head to feet (as wide as the old circle, a bit taller);
  walls still collide with the round body, so every corridor stays passable.
- Respawn 3 s after death in your team's spawn zone, with 3 s of invulnerability (flashing).
- You can't be damaged while inside your own team's spawn zone (shield ring) — but bullets fired from inside your spawn
  stop at its edge, so to shoot anyone you have to step out and expose yourself.
- You can't walk into another team's spawn zone.
- Kill = 10 points. Team score = total kills by its members. Highest team score wins when the timer hits zero.
- Players who arrive while a match is running can pick a team with a free slot and jump straight in,
  or stay on the team screen and wait for the next match.
- Refreshing the browser (or a Wi-Fi hiccup) during a match reconnects you to your player (same team and stats).

## Maps

Every sub-folder of `Maps/` is a map; the admin chooses one before a match and players see a preview in the lobby.
A map folder holds the background image and a `map.json` describing its collision geometry **in image pixels**:

```json
{
  "name": "Galadriel",
  "image": "Map.jpg",
  "image_size": [2048, 2048],
  "world_size": [1600, 900],
  "walls": [[x, y, width, height], ...],
  "spawn_zones": [[x, y, width, height], [x, y, width, height]]
}
```

- `walls` are solid rectangles (include the outer border; an L-shape is two rectangles).
- `spawn_zones` lists one zone per team, in the order of `TEAMS` (first = TEAM A).
- `world_size` is the game-world size the image is stretched to. 1600×900 (16:9) fills a typical screen.
- Open `http://localhost:8000/?debug=1` to see the collision rectangles drawn over the art and check they line up.
- `python -m pytest tests/test_maps.py` validates every map (loads, spawns fit a full team, all open areas reachable).

## Configuration

All tuning values (health, speeds, cooldown, respawn delay, team size, tick rate, default map, …)
and the team list are in [game/config.py](game/config.py).
To add a team, add an entry to `TEAMS` and a matching spawn zone to every map's `spawn_zones`.

## Troubleshooting

- If a player's page loads but JOIN does nothing, their browser is probably using files cached from an
  older version: have them hard-refresh (Ctrl+F5) once. The server tells browsers to always check for
  updates, so this should only happen with files cached before that was added.

- The server writes `server.log` next to `server.py`. If the game ever freezes, look for
  `Game loop stalled` or `Dropping player …` lines there.
- On Windows the server turns off the console's QuickEdit mode, because selecting text in the console window
  pauses the whole server. If you start it some other way, avoid clicking inside its console window.

## Stress test

With the server running (`$env:LAN_SHOOTER_ADMIN_PASSWORD = "test"; python server.py`):

```bash
python tools/stress_test.py --password test --seconds 60
```

It runs 11 bots plus a client that stops reading, a client whose connection drops and resumes,
a mid-match joiner and enough extra players to fill the server, then reports snapshot timing and PASS/FAIL checks.

## Tests

```bash
python -m pytest            # all tests
python -m pytest tests/test_game.py::test_walls_block_bullets   # a single test
```

## Project layout

```
server.py            HTTP routes, WebSocket networking, admin API, fixed-rate game loop
game/config.py       GAME_CONFIG, TEAMS, MAPS_DIR
game/maps.py         loads Maps/<Name>/map.json (pixel -> world coordinates)
game/game.py         authoritative game state and rules (no I/O)
game/collision.py    geometry helpers
game/entities.py     Player / Bullet data
static/              browser client (index.html, client.js, render.js) and admin page
Maps/                one folder per map (image + map.json)
tools/stress_test.py multi-client load/robustness test against a running server
tests/               pytest suite
```
