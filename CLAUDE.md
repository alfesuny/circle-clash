# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state & how to use this file

V1 (all phases in §38) is implemented. Everything below the `---` line is the owner's original product spec.

### Commands (Windows; venv already created in `.venv`)

- Run server: `.venv/Scripts/python server.py` (binds `0.0.0.0:8000`, prints LAN URL + admin password). Set `LAN_SHOOTER_ADMIN_PASSWORD` for a fixed password; otherwise it is random per run.
- All tests: `.venv/Scripts/python -m pytest`
- Single test: `.venv/Scripts/python -m pytest tests/test_game.py::test_walls_block_bullets`
- Install deps: `.venv/Scripts/python -m pip install -r requirements.txt`

### Architecture

- `game/game.py` — `Game` class: the single authoritative state + all rules. No I/O. Every time-dependent method takes an optional `now` (monotonic seconds) so tests drive time explicitly. Refusals raise `GameError` (message shown to user).
- `server.py` — FastAPI app holding one global `game`. A background `game_loop` ticks at `tick_rate` and broadcasts the same `game.snapshot()` JSON to every socket. `/ws` handles client messages (`join`, `team`, `move`, `aim`, `shoot`); `/api/admin/*` are REST endpoints guarded by an in-memory token from `/api/admin/login` (header `X-Admin-Token`). Socket cleanup/`game.disconnect` happens only in the `/ws` receive loop's `finally`.
- `game/config.py` — `GAME_CONFIG`, `TEAMS`, `MAP`. Teams are data; a new team needs a `TEAMS` entry and a `MAP["spawn_zones"]` entry.
- `static/client.js` — screens (join/waiting/lobby/game/results) are derived from each snapshot in `updateScreens()`. Renders one tick behind, interpolating between the last two snapshots; only the local aim angle is computed client-side. Session (`id` + `resume_token`) lives in `sessionStorage` so a refresh mid-match calls `Game.resume`.
- `static/render.js` — pure canvas drawing in world coordinates, scaled to fit.
- Disconnect semantics: in LOBBY the player is deleted; mid-match they are kept (stats retained, `connected=False`, not rendered/targetable) and purged on the next start/lobby reset. `team_kills` is tracked separately from player kills so a leaver's kills still count for their team.

### Non-negotiable constraints (summarized from the spec)

- **Stack:** Python + FastAPI + WebSockets + Uvicorn backend; vanilla HTML/CSS/JS + Canvas frontend served by the Python server. No React/game engines/extra frameworks.
- **Server-authoritative:** clients send only input (`move` keys, `aim` angle, `shoot`); the server owns positions, collisions, bullets, damage, kills, respawns, timer, and scores. Never trust client-reported outcomes.
- **Fixed server tick** (~20–30 Hz) driving the update order in §31; game logic must not depend on client message rate.
- **Data-driven:** teams, map (walls, spawn zones as rectangles), and all tuning values live in central config (`GAME_CONFIG`, `MAP`) — never hard-code three teams or scatter constants.
- **World coordinates** (e.g. 1000×700) on the server; the client only scales for rendering.
- **Explicit game states** `LOBBY → RUNNING → ENDED → LOBBY`; team changes only in LOBBY; new joins rejected during RUNNING.
- **Keep concerns separated:** networking, game state, game rules, collision, frontend rendering, admin UI.
- Respect §41 "What NOT to Build Yet".

---

# LAN Multiplayer 2D Shooter — Development Handoff

## 1. Project Overview

I want to build a small, browser-based, multiplayer 2D shooter game that runs locally on my computer.

The goal is to be able to start the game server on my machine and have other people on the same local network/Wi-Fi join using my computer's local IP address.

For example:

```text
http://192.168.1.105:8000
```

Players should not need to install anything. They should simply open the URL in their browser.

The game should be intentionally simple:

* 2D only
* Browser-based
* Players represented by simple colored circles
* Top-down view
* Mouse-based aiming
* Click to shoot
* Keyboard-based movement
* Walls/obstacles
* Team-based gameplay
* Health/damage
* Death and respawn
* Protected spawn areas
* Fixed-duration matches
* Team and individual scoring
* Admin-controlled game start
* Local LAN multiplayer

This is NOT intended to be a polished commercial game. The priority is a fun, reliable LAN multiplayer prototype that is easy to understand and extend.

---

# 2. Recommended Technology

Use:

### Backend

* Python
* FastAPI
* WebSockets
* Uvicorn

Python should be responsible for the authoritative game state and game logic.

### Frontend

* HTML
* CSS
* Vanilla JavaScript
* HTML5 Canvas

Do NOT introduce React, Unity, Godot, or another game engine unless there is a compelling technical reason.

The frontend should be lightweight and served directly by the Python server.

---

# 3. Basic Architecture

The architecture should be:

```text
                         HOST COMPUTER
                    ┌─────────────────────┐
                    │     Python Server   │
                    │                     │
                    │      FastAPI        │
                    │      WebSockets     │
                    │                     │
                    │  Game State         │
                    │  Players            │
                    │  Teams              │
                    │  Bullets            │
                    │  Collision          │
                    │  Health             │
                    │  Respawns           │
                    │  Scores             │
                    │  Timer              │
                    └──────────┬──────────┘
                               │
                         Local Network
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
          Browser 1        Browser 2        Browser 3
          Player A         Player B         Player C
```

The server must be authoritative.

Clients should send input/events to the server, rather than being trusted to determine game outcomes.

For example, a client can send:

```json
{
  "type": "shoot",
  "angle": 1.27
}
```

The server determines whether the shot is valid and whether it hits another player.

---

# 4. Initial Game Limits

Start with:

```text
3 teams
5 players maximum per team
15 players maximum total
```

The three initial teams are:

```text
RED
GREEN
BLUE
```

The architecture should make it easy to add more teams later.

Do not hard-code the entire game around exactly three teams.

Represent teams as configurable data.

---

# 5. Player Joining

When a player visits:

```text
http://<HOST_LOCAL_IP>:8000
```

they should see a simple landing/join screen.

For example:

```text
┌───────────────────────────────┐
│        LAN SHOOTER            │
│                               │
│  Enter your name:             │
│  [________________]            │
│                               │
│       [ JOIN GAME ]           │
└───────────────────────────────┘
```

The player enters a display name.

The server assigns a unique player ID.

Player IDs must NOT depend on the player's name.

---

# 6. Team Selection

After joining, players should choose a team.

Example:

```text
Choose Your Team

🔴 RED
3 / 5 players

🟢 GREEN
2 / 5 players

🔵 BLUE
4 / 5 players
```

Players can choose any team that has available capacity.

Maximum:

```text
5 players per team
```

If a team is full, it should be disabled.

Players should be able to change teams before the game starts.

Once the admin starts the game:

* Team selection is locked.
* Players cannot switch teams during the match.

If a player joins after the game has already started, handle this explicitly.

Preferred initial behavior:

> Do not allow new players to join an active match. Show them that the game is currently in progress and they must wait for the next match.

This can be changed later if needed.

---

# 7. Admin System

There should be a separate admin interface.

The admin is the person running the Python server.

The admin should have a simple password-protected admin page.

For example:

```text
/admin
```

The admin interface should show:

```text
LAN SHOOTER — ADMIN

Players
────────────────────────

RED       3 / 5
GREEN     4 / 5
BLUE      2 / 5

Total: 9 / 15

Game Duration:
[ 05:00 ]

[ START GAME ]
```

The admin controls the match.

---

# 8. Admin Can Start With Any Number of Players

The lobby does NOT need to be full.

For example:

```text
RED      2
GREEN    2
BLUE     1

Total: 5 players
```

The admin should still be able to click:

```text
START GAME
```

The game starts immediately.

Do not require:

```text
15 / 15 players
```

before starting.

---

# 9. Admin Timer

The admin should be able to set the match duration before starting.

For example:

```text
Game Duration:

Minutes: [ 5 ]
Seconds: [ 00 ]
```

Or a simple duration input.

Default:

```text
5 minutes
```

But the admin should be able to change it.

Examples:

```text
1 minute
5 minutes
10 minutes
15 minutes
```

Once the game starts, the timer is controlled by the server.

The client should not be trusted to maintain the official timer.

---

# 10. Game Map

The game is a top-down 2D arena.

Players are simple circles.

The map should contain fixed rectangular walls/obstacles.

Example:

```text
┌──────────────────────────────────────────┐
│                                          │
│  SPAWN RED                               │
│  █████                                   │
│                                          │
│          █████████                       │
│          █████████                       │
│                                          │
│                       ███████             │
│                       ███████             │
│                                          │
│                ███                       │
│                ███                       │
│                                          │
│                            SPAWN BLUE     │
│                            █████          │
│                                          │
└──────────────────────────────────────────┘
```

Walls should be rectangular for the initial implementation.

The map should be defined as data, rather than having collision geometry hard-coded throughout the game logic.

For example:

```python
MAP = {
    "width": 1000,
    "height": 700,

    "walls": [
        {
            "x": 300,
            "y": 150,
            "width": 200,
            "height": 30
        },
        ...
    ],

    "spawn_zones": {
        "red": {...},
        "green": {...},
        "blue": {...}
    }
}
```

This will make it easy to create additional maps later.

---

# 11. Player Movement

Players should move using:

```text
W
A
S
D
```

Movement should be continuous.

Example:

```text
W = up
A = left
S = down
D = right
```

Players should not be able to move outside the game map.

Players should also not be able to walk through walls.

Collision must be handled by the server.

The client can predict/render movement for responsiveness, but the server must remain authoritative.

---

# 12. Player Representation

Keep players extremely simple.

A player should be represented by a circle.

Team determines the circle color:

```text
RED   → red circle
GREEN → green circle
BLUE  → blue circle
```

Player names can optionally appear above their circles:

```text
       Suny
        🔴
```

Do not add character models or sprites initially.

---

# 13. Aiming

Players aim using their mouse.

The mouse position determines the direction of the weapon.

For example:

```text
       mouse
         X
        /
       /
      🔴
```

The player shoots in the direction of the mouse.

The frontend can calculate the angle:

```javascript
angle = Math.atan2(
    mouseY - playerY,
    mouseX - playerX
);
```

The client sends the shooting input to the server.

The server determines the actual bullet trajectory.

---

# 14. Shooting

Initial shooting mechanics should be extremely simple.

Mouse click:

```text
CLICK
  ↓
CREATE BULLET
  ↓
MOVE BULLET
  ↓
CHECK WALL COLLISION
  ↓
CHECK PLAYER COLLISION
```

Bullets should travel in a straight line.

No complicated weapons are required for V1.

Use one basic weapon for everybody.

No ammunition/reloading initially.

A small fire-rate/cooldown should exist so that players cannot send thousands of shots per second.

For example:

```text
1 shot every 200–300 ms
```

The exact value can be tuned later.

---

# 15. Bullet Collision With Walls

Walls must block bullets.

Example:

```text
RED PLAYER                  BLUE PLAYER

    🔴  ────────►  █████████  ────────► 🔵
                    WALL
```

The bullet should hit the wall and disappear.

It must NOT continue through the wall.

This is an important gameplay mechanic because players should have to move around obstacles to attack enemies.

---

# 16. Bullet Collision With Players

Bullets should damage players from other teams.

A bullet hitting an enemy should:

```text
enemy.health -= 1
```

Friendly fire should initially be disabled.

Therefore:

```text
RED → RED
```

does nothing.

But:

```text
RED → GREEN
RED → BLUE
```

can cause damage.

---

# 17. Health

Give every player a small amount of health.

Recommended initial value:

```text
4 HP
```

Therefore:

```text
4 successful hits = death
```

HUD could show:

```text
HP: ♥ ♥ ♥ ♥
```

or:

```text
HP: 4 / 4
```

The exact health value should ideally be configurable.

---

# 18. Death

When:

```text
health <= 0
```

the player dies.

The player should:

* Stop being able to move/shoot temporarily.
* Be visually marked as dead or disappear.
* Have their death recorded.
* Award a kill to the player who made the final hit.
* Be scheduled for respawn.

Do not permanently remove the player from the game.

---

# 19. Respawning

Players should respawn after a short delay.

Recommended:

```text
3 seconds
```

Example:

```text
YOU DIED

Respawning in...

3
2
1

RESPAWN
```

When respawning, place the player at a valid spawn location for their team.

Avoid spawning players directly on top of each other if possible.

---

# 20. Spawn Zones

Each team has a designated spawn zone.

For example:

```text
RED SPAWN
GREEN SPAWN
BLUE SPAWN
```

Spawn zones should be represented as rectangular areas.

Players should spawn inside their team's zone.

---

# 21. Spawn Protection

Spawn zones are protected.

Players inside their own spawn zone should not be damageable.

Example:

```text
             BULLET
RED ─────────────────────►

                         ┌─────────────┐
                         │ BLUE SPAWN  │
                         │             │
                         │     🔵      │
                         │             │
                         └─────────────┘

                         DAMAGE = 0
```

Additionally, players should receive temporary spawn protection after respawning.

Recommended:

```text
3 seconds
```

During those 3 seconds:

```text
player.invulnerable = True
```

Display this visually if practical, for example with:

* flashing circle
* shield icon
* transparency

After 3 seconds:

```text
player.invulnerable = False
```

This prevents spawn camping.

---

# 22. Important Spawn Rule

Players should NOT be able to exploit spawn protection by sitting inside their spawn forever.

For the initial version, simply make spawn zones safe.

Later we can add mechanics such as:

* score penalties
* forced movement
* limited spawn-zone time
* enemies cannot enter spawn zones
* spawn zones only protect recently spawned players

Do not overcomplicate V1.

---

# 23. Server-Authoritative Game State

This is important.

The server should own:

```text
player position
player health
player alive/dead state
team
bullets
bullet positions
bullet ownership
hits
kills
deaths
respawn timers
game timer
game state
team scores
```

Clients should primarily send input:

```text
movement
aim direction
shoot
```

Do NOT trust a client saying:

```text
"I killed Player X."
```

The server should calculate whether the hit actually happened.

---

# 24. Game States

Implement explicit game states.

At minimum:

```text
LOBBY
RUNNING
ENDED
```

Potentially:

```text
LOBBY
  ↓
RUNNING
  ↓
ENDED
  ↓
LOBBY
```

### LOBBY

Players can:

* Join
* Choose teams
* Change teams
* See team counts

Admin can:

* Set timer
* Start game

### RUNNING

Players can:

* Move
* Shoot
* Kill
* Die
* Respawn

Players cannot:

* Change teams
* Leave/rejoin the match and retain arbitrary state

Admin can:

* End game early

### ENDED

Show results.

Players cannot move/shoot.

Admin can:

```text
START NEW GAME
```

which resets the match.

---

# 25. Score System

Track individual player statistics.

At minimum:

```text
kills
deaths
```

Potentially:

```text
shots
hits
damage
```

but these are optional for V1.

Recommended initial scoring:

```text
Kill = 10 points
```

Deaths do not need to subtract points initially.

Individual score:

```text
score = kills * 10
```

---

# 26. Team Score

Team score should be based on kills by members of that team.

Example:

```text
RED
Player A: 10 kills
Player B: 7 kills
Player C: 4 kills

Team Red = 21 kills
```

Display:

```text
RED      21
GREEN    17
BLUE     12
```

The team with the highest score at the end wins.

---

# 27. End-of-Game Results

When the timer reaches zero:

```text
GAME OVER
```

Stop all game activity.

Show a results screen.

Example:

```text
╔══════════════════════════════════════╗
║              GAME OVER               ║
║                                      ║
║           🏆 RED TEAM WINS           ║
║                                      ║
║ TEAM SCORES                           ║
║                                      ║
║ 🔴 RED       84 kills                ║
║ 🟢 GREEN     71 kills                ║
║ 🔵 BLUE      63 kills                ║
║                                      ║
║ PLAYER SCORES                        ║
║                                      ║
║ 1. Suny       🔴    24 kills         ║
║ 2. John       🔵    19 kills         ║
║ 3. Alex       🟢    17 kills         ║
║ 4. Bob        🔴    16 kills         ║
║ ...                                  ║
║                                      ║
║       WAITING FOR NEXT GAME          ║
╚══════════════════════════════════════╝
```

Show both:

1. Team leaderboard
2. Individual leaderboard

Sort individual players by score/kills.

---

# 28. HUD During Game

Keep the UI minimal.

Something like:

```text
┌──────────────────────────────────────────────┐
│ RED: 42     GREEN: 38     BLUE: 35   03:21  │
│                                              │
│                                              │
│                 GAME MAP                     │
│                                              │
│                                              │
│                                              │
│                                              │
│                                              │
│                                              │
│ HP: ♥ ♥ ♥ ♥                 Kills: 7         │
└──────────────────────────────────────────────┘
```

The player should always see:

* Remaining time
* Team scores
* Their health
* Their kills

---

# 29. Rendering

Use HTML Canvas.

The game should render:

1. Background
2. Walls
3. Spawn zones
4. Bullets
5. Players
6. Player names
7. HUD

Keep graphics intentionally simple.

No images are necessary for V1.

Use:

* circles
* rectangles
* text
* simple effects

---

# 30. Map Coordinate System

Use a consistent world coordinate system.

For example:

```text
width = 1000
height = 700
```

The server operates in world coordinates.

The client canvas scales the world to the browser window.

Do not tie game physics directly to browser pixel dimensions.

This will make the game more reliable across different screen sizes.

---

# 31. Game Loop

The server should have a fixed update loop/tick.

For example:

```text
20–30 updates per second
```

At each tick:

```text
1. Process player movement
2. Validate movement
3. Move bullets
4. Check bullet/wall collisions
5. Check bullet/player collisions
6. Apply damage
7. Process deaths
8. Process respawns
9. Update timer
10. Broadcast game state
```

The exact tick rate can be tuned.

Do not make the game dependent on how frequently a browser sends messages.

---

# 32. WebSocket Communication

Use WebSockets for real-time game communication.

Define a clean message protocol.

For example, client → server:

```json
{
  "type": "move",
  "keys": {
    "w": true,
    "a": false,
    "s": false,
    "d": false
  }
}
```

Aiming:

```json
{
  "type": "aim",
  "angle": 1.57
}
```

Shooting:

```json
{
  "type": "shoot"
}
```

Server → client:

```json
{
  "type": "state",
  "players": [...],
  "bullets": [...],
  "scores": {...},
  "time_remaining": 213,
  "game_state": "RUNNING"
}
```

Define these message types cleanly rather than passing arbitrary unstructured JSON everywhere.

---

# 33. Connection Handling

The server must handle:

* Player connecting
* Player disconnecting
* Browser refresh
* Player leaving
* WebSocket failure

If a player disconnects during the lobby:

Remove them.

If they disconnect during the game:

Mark them disconnected and remove them from active gameplay.

Do not let disconnected players remain as invisible blockers or targets.

---

# 34. Admin Authentication

Implement a simple admin password.

It does NOT need enterprise-grade authentication.

This is a local LAN game.

But players should not be able to simply open `/admin` and control the game.

Use a simple authenticated admin session/token.

Keep the implementation clean enough that it can be replaced later if needed.

---

# 35. LAN Hosting

The server must bind to:

```text
0.0.0.0
```

not just:

```text
127.0.0.1
```

Example:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

The host can then find their local IP:

```text
192.168.x.x
```

Other users on the same LAN can visit:

```text
http://192.168.x.x:8000
```

Document this in the README.

Mention that the host computer's firewall may need to allow Python/port 8000.

---

# 36. Important Security Assumption

This is a LAN game.

Do not spend time building internet-grade security, matchmaking infrastructure, accounts, NAT traversal, etc.

The intended environment is:

```text
One computer runs the server.
Multiple people on the same local network connect to it.
```

The server should still validate gameplay inputs to prevent accidental or trivial client cheating.

---

# 37. UI Philosophy

The UI should be simple and functional.

Do NOT spend significant time on visual polish initially.

Use a clean dark interface with:

* clear buttons
* large team selection buttons
* readable scores
* clear timer
* obvious game state

The actual game should occupy most of the screen.

---

# 38. Development Strategy

DO NOT try to implement the entire game in one giant step.

Build and test incrementally.

## Phase 1 — Basic Server

Create:

```text
server.py
```

and serve:

```text
index.html
```

Verify:

```text
http://localhost:8000
```

works.

---

## Phase 2 — WebSocket Connection

Implement WebSocket connection.

Open two browser tabs.

Verify the server sees:

```text
Player 1 connected
Player 2 connected
```

---

## Phase 3 — Players

Create player objects.

Each player gets:

```text
id
name
team
x
y
health
alive
kills
deaths
```

Render them as circles.

Open two browsers and verify:

> Player A can see Player B.

---

## Phase 4 — Movement

Implement:

```text
WASD
```

Verify players can move.

Add map boundaries.

---

## Phase 5 — Teams

Add:

```text
RED
GREEN
BLUE
```

Implement team selection.

Add maximum:

```text
5 players/team
```

---

## Phase 6 — Map and Walls

Add:

* walls
* collision with walls
* spawn zones

Verify:

> Players cannot walk through walls.

---

## Phase 7 — Shooting

Add:

* mouse aiming
* click to shoot
* bullets
* bullet movement

Verify:

> Player A can shoot toward Player B.

---

## Phase 8 — Bullet/Wall Collision

Verify:

```text
bullet → wall → disappears
```

and:

```text
bullet → wall → player behind wall
```

does NOT damage the player.

---

## Phase 9 — Damage

Implement:

```text
4 HP
```

Every enemy hit:

```text
HP -= 1
```

Verify the player dies after 4 valid hits.

---

## Phase 10 — Death/Respawn

Implement:

```text
death
↓
3 second respawn timer
↓
team spawn
```

Add spawn protection.

---

## Phase 11 — Scoring

Implement:

```text
kills
deaths
player score
team score
```

Verify team score increases when a team member gets a kill.

---

## Phase 12 — Admin

Build:

```text
/admin
```

with:

* password
* player list
* team counts
* timer setting
* Start Game
* End Game

---

## Phase 13 — Match Timer

Implement server-controlled timer.

Default:

```text
5 minutes
```

Admin can change it before starting.

When timer reaches:

```text
00:00
```

automatically end the match.

---

## Phase 14 — Results Screen

Display:

* winning team
* all team scores
* player rankings
* kills
* deaths

---

## Phase 15 — LAN Testing

Test with multiple devices.

At minimum:

```text
Host computer
+ 2 additional computers/phones
```

Then test with more clients.

Eventually test toward:

```text
10–15 simultaneous players
```

Check:

* movement synchronization
* shooting
* collisions
* disconnects
* respawning
* timer
* scoreboard

---

# 39. Testing Priorities

Prioritize correctness over visuals.

Important tests:

### Teams

* Cannot exceed 5 players.
* Full teams cannot accept players.
* Players can change teams before game starts.
* Players cannot change teams during the game.

### Movement

* Cannot leave map.
* Cannot walk through walls.

### Shooting

* Cannot shoot before game starts.
* Cannot shoot after game ends.
* Cannot damage teammates.
* Walls block bullets.
* Dead players cannot shoot.
* Fire-rate limit works.

### Damage

* Correct HP reduction.
* Four hits kill.
* Correct killer receives kill.
* Correct victim receives death.

### Spawn

* Correct team spawn.
* Spawn protection works.
* Players cannot be damaged inside protected spawn zone.

### Timer

* Server controls timer.
* Match ends automatically.
* Scores remain available after match ends.

### Admin

* Only admin can start/end game.
* Admin can start with fewer than 15 players.
* Admin can configure timer.

---

# 40. Keep Configuration Centralized

Create a configuration section such as:

```python
GAME_CONFIG = {
    "max_players_per_team": 5,
    "teams": ["red", "green", "blue"],
    "default_game_duration": 300,
    "player_health": 4,
    "respawn_delay": 3,
    "spawn_protection_duration": 3,
    "player_speed": ...,
    "bullet_speed": ...,
    "fire_cooldown": ...,
    "kill_score": 10
}
```

Do not scatter these values throughout the code.

This will make game balancing much easier later.

---

# 41. What NOT to Build Yet

Do not add these unless specifically requested later:

* User accounts
* Database
* Matchmaking
* Internet multiplayer
* Voice chat
* Inventory
* Multiple weapons
* Reloading
* Powerups
* Character sprites
* 3D
* Physics engine
* Complex animations
* AI bots
* Ranking system
* Persistent player profiles
* Cloud deployment

The first goal is a reliable LAN multiplayer game.

---

# 42. Definition of Done for V1

V1 is complete when the following scenario works:

1. I start the Python server on my computer.
2. Other people on the same Wi-Fi open my local IP.
3. They enter their names.
4. They see the lobby.
5. They choose RED, GREEN, or BLUE.
6. Maximum 5 players can join each team.
7. I open the admin panel.
8. I see all connected players and team counts.
9. I set the match duration.
10. I click START GAME.
11. The game starts even if there are fewer than 15 players.
12. Players move around using WASD.
13. Players aim with their mouse.
14. Players click to shoot.
15. Bullets travel through open space.
16. Walls block bullets.
17. Players cannot walk through walls.
18. Players have 4 HP.
19. Four valid enemy hits kill a player.
20. Players respawn after approximately 3 seconds.
21. Spawn zones prevent damage.
22. Newly respawned players have temporary protection.
23. Kills and deaths are tracked.
24. Team scores are tracked.
25. The timer counts down.
26. When the timer reaches zero, the game stops.
27. A results screen appears.
28. The winning team is shown.
29. Team scores are shown.
30. Individual player scores are shown.
31. The admin can start another game.

---

# 43. Implementation Philosophy

Keep the code:

* Modular
* Readable
* Small
* Easy to modify
* Well-commented where game logic is non-obvious

Avoid unnecessary frameworks.

Avoid premature optimization.

Avoid creating a huge architecture for a simple game.

However, do separate:

```text
networking
game state
game rules
collision
frontend rendering
admin UI
```

so the project remains maintainable.

Most importantly:

**Build incrementally and test each phase before moving to the next.**

If something is broken, fix it before adding another major feature.

The final product should feel like a simple LAN party shooter rather than an over-engineered software project.
