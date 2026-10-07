// Game client: networking, input and UI screens. The server is authoritative;
// this file only sends input and displays the state the server broadcasts.
(() => {
  const $ = (id) => document.getElementById(id);
  const SESSION_KEY = "lanshooter-session";

  let ws = null;
  let hello = null;          // {config, map, teams} sent by the server on connect
  let me = null;             // {id, name, token} once joined
  let waitingJoin = null;    // {name, reason} when the join was refused but can be retried
  let lastJoinAttempt = 0;
  let prevSnap = null, snap = null; // last two server snapshots, for interpolation
  let snapTime = 0;
  let resultsKey = null;
  let missingSince = 0;

  const keys = { w: false, a: false, s: false, d: false };
  let mouse = null;          // last mouse position (client coords)
  let aimAngle = 0;
  let lastAimSent = 0, lastAimValue = null;
  let firing = false, lastShotSent = 0;

  // ------------------------------------------------------------ session
  function loadSession() {
    try { return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || null; } catch { return null; }
  }
  function saveSession(s) {
    try { s ? sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)) : sessionStorage.removeItem(SESSION_KEY); } catch {}
  }

  // ------------------------------------------------------------ networking
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => $("conn-banner").classList.add("hidden");
    ws.onmessage = (ev) => handle(JSON.parse(ev.data));
    ws.onclose = () => {
      me = null;
      snap = prevSnap = null;
      if (loadSession()) $("conn-banner").classList.remove("hidden");
      setTimeout(connect, 1000);
    };
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }

  function sendJoin(name) {
    const s = loadSession();
    const resume = s && s.id && s.token ? { id: s.id, token: s.token } : null;
    lastJoinAttempt = performance.now();
    send({ type: "join", name, resume });
  }

  function handle(msg) {
    switch (msg.type) {
      case "hello": {
        hello = msg;
        Render.init($("canvas"), msg.map, msg.config, msg.teams);
        buildTeamButtons();
        const s = loadSession();
        if (s && s.name) sendJoin(s.name); // refresh / reconnect: rejoin automatically
        updateScreens();
        break;
      }
      case "welcome":
        me = { id: msg.player_id, name: msg.name, token: msg.resume_token };
        waitingJoin = null;
        saveSession({ name: msg.name, id: msg.player_id, token: msg.resume_token });
        $("lobby-name").textContent = msg.name;
        updateScreens();
        break;
      case "join_rejected":
        if (msg.retry) {
          waitingJoin = { name: (loadSession() || {}).name || $("name-input").value, reason: msg.reason };
        } else {
          waitingJoin = null;
          saveSession(null);
          $("join-error").textContent = msg.reason;
        }
        updateScreens();
        break;
      case "error":
        $("lobby-error").textContent = msg.message;
        setTimeout(() => ($("lobby-error").textContent = ""), 3000);
        break;
      case "state":
        prevSnap = snap;
        snap = msg;
        snapTime = performance.now();
        onState();
        break;
    }
  }

  function myPlayer() {
    return snap && me ? snap.players.find((p) => p.id === me.id) : null;
  }

  function onState() {
    // Refused earlier (match running / server full)? Retry when it may succeed.
    if (!me && waitingJoin && snap.game_state !== "RUNNING" && performance.now() - lastJoinAttempt > 1500) {
      sendJoin(waitingJoin.name);
    }
    if (me && !myPlayer()) {
      // The server no longer knows us (e.g. it restarted): start over. A short
      // grace period ignores a snapshot that was in flight while we joined.
      missingSince = missingSince || performance.now();
      if (performance.now() - missingSince > 1000) {
        me = null;
        missingSince = 0;
        saveSession(null);
      }
    } else {
      missingSince = 0;
    }
    updateScreens();
  }

  // ------------------------------------------------------------ screens
  let currentScreen = null;
  function show(id) {
    if (id === currentScreen) return;
    currentScreen = id;
    for (const s of document.querySelectorAll(".screen")) s.classList.toggle("hidden", s.id !== id);
    if (id === "screen-game") Render.resize();
  }

  function fmtTime(sec) {
    sec = Math.max(0, Math.ceil(sec));
    return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
  }

  function liveTimeRemaining() {
    if (!snap) return 0;
    const elapsed = snap.game_state === "RUNNING" ? (performance.now() - snapTime) / 1000 : 0;
    return snap.time_remaining - elapsed;
  }

  function updateScreens() {
    if (!hello) return;
    if (!me) {
      if (waitingJoin) {
        $("waiting-text").textContent = waitingJoin.reason + " You'll join automatically when possible.";
        show("screen-waiting");
      } else {
        show("screen-join");
      }
      return;
    }
    if (!snap) return;
    const p = myPlayer();
    if (!p) return;
    if (snap.game_state === "LOBBY") {
      updateLobby(p);
      show("screen-lobby");
    } else if (snap.game_state === "RUNNING" && !p.in_match) {
      $("waiting-text").textContent = "A match started before you picked a team. You'll be able to join the next one.";
      show("screen-waiting");
    } else if (snap.game_state === "ENDED" && !p.in_match) {
      updateLobby(p);
      show("screen-lobby");
      $("lobby-status").textContent = "The last match just ended. Pick a team for the next one!";
    } else {
      updateHud(p);
      show("screen-game");
    }
  }

  // ------------------------------------------------------------ lobby
  function buildTeamButtons() {
    const box = $("team-buttons");
    box.innerHTML = "";
    for (const t of hello.teams) {
      const b = document.createElement("button");
      b.className = "team-btn";
      b.dataset.team = t.id;
      b.style.borderColor = t.color;
      b.innerHTML = `<div class="team-name"></div><div class="team-count"></div><div class="team-members"></div>`;
      b.querySelector(".team-name").textContent = t.name;
      b.querySelector(".team-name").style.color = t.color;
      b.addEventListener("click", () => send({ type: "team", team: t.id }));
      box.appendChild(b);
    }
  }

  function updateLobby(p) {
    for (const t of snap.teams) {
      const b = document.querySelector(`.team-btn[data-team="${t.id}"]`);
      if (!b) continue;
      const mine = p.team === t.id;
      b.classList.toggle("selected", mine);
      b.disabled = !mine && t.count >= t.max;
      b.querySelector(".team-count").textContent = `${t.count} / ${t.max} players${mine ? " — YOU" : ""}`;
      b.querySelector(".team-members").textContent = snap.players
        .filter((q) => q.team === t.id).map((q) => q.name).join(", ");
    }
    $("lobby-status").textContent = p.team
      ? "Waiting for the admin to start the game…"
      : "Pick a team to play in the next match.";
  }

  // ------------------------------------------------------------ HUD
  function teamById(id) { return hello.teams.find((t) => t.id === id); }

  function updateHud(p) {
    const scores = $("hud-scores");
    scores.innerHTML = "";
    for (const t of snap.teams) {
      const s = document.createElement("span");
      s.style.color = t.color;
      s.textContent = `${t.name}: ${t.kills}`;
      scores.appendChild(s);
    }
    const max = hello.config.player_health;
    const hp = Math.max(0, p.health || 0);
    $("hud-health").textContent = "HP: " + "♥ ".repeat(hp) + "♡ ".repeat(max - hp);
    $("hud-kills").textContent = `Kills: ${p.kills}   Deaths: ${p.deaths}`;

    const dead = snap.game_state === "RUNNING" && !p.alive;
    $("death-overlay").classList.toggle("hidden", !dead);
    if (dead && p.respawn_in != null) $("respawn-count").textContent = Math.max(1, Math.ceil(p.respawn_in));

    const feed = $("kill-feed");
    feed.innerHTML = "";
    for (const k of snap.kill_feed) {
      const row = document.createElement("div");
      const a = document.createElement("span"), b = document.createElement("span");
      a.textContent = k.killer; a.style.color = (teamById(k.killer_team) || {}).color;
      b.textContent = k.victim; b.style.color = (teamById(k.victim_team) || {}).color;
      row.append(a, " ➜ ", b);
      feed.appendChild(row);
    }

    const ended = snap.game_state === "ENDED" && snap.results;
    $("results-overlay").classList.toggle("hidden", !ended);
    if (ended) renderResults(snap.results);
    else resultsKey = null;
  }

  function el(tag, text, attrs = {}) {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    Object.assign(e, attrs);
    return e;
  }

  function teamCell(teamId) {
    const t = teamById(teamId) || { name: "?", color: "#888" };
    const td = el("td");
    const dot = el("span", null, { className: "dot" });
    dot.style.background = t.color;
    td.append(dot, t.name);
    return td;
  }

  function renderResults(r) {
    const key = JSON.stringify(r);
    if (key === resultsKey) return;
    resultsKey = key;
    const box = $("results-overlay");
    box.innerHTML = "";
    box.append(el("h2", "GAME OVER"));

    let winText = "DRAW";
    if (r.winners.length === 1) {
      winText = `🏆 ${(teamById(r.winners[0]) || { name: "?" }).name} TEAM WINS`;
    }
    const win = el("div", winText, { className: "winner" });
    if (r.winners.length === 1) win.style.color = teamById(r.winners[0]).color;
    box.append(win);

    box.append(el("h3", "TEAM SCORES"));
    const tt = el("table");
    tt.append(rowOf("th", ["Team", "Kills"]));
    for (const t of r.teams) {
      const tr = el("tr");
      tr.append(teamCell(t.id), el("td", t.kills));
      tt.append(tr);
    }
    box.append(tt);

    box.append(el("h3", "PLAYER SCORES"));
    const pt = el("table");
    pt.append(rowOf("th", ["#", "Player", "Team", "Kills", "Deaths", "Score"]));
    r.players.forEach((p, i) => {
      const tr = el("tr");
      if (me && p.id === me.id) tr.className = "me";
      tr.append(el("td", i + 1), el("td", p.name + (p.connected ? "" : " (left)")), teamCell(p.team),
        el("td", p.kills), el("td", p.deaths), el("td", p.score));
      pt.append(tr);
    });
    box.append(pt);
    box.append(el("p", "WAITING FOR NEXT GAME", { className: "muted" }));
  }

  function rowOf(cellTag, values) {
    const tr = el("tr");
    for (const v of values) tr.append(el(cellTag, v));
    return tr;
  }

  // ------------------------------------------------------------ input
  const KEY_MAP = { KeyW: "w", ArrowUp: "w", KeyA: "a", ArrowLeft: "a", KeyS: "s", ArrowDown: "s", KeyD: "d", ArrowRight: "d" };

  function setKey(code, down) {
    const k = KEY_MAP[code];
    if (!k || keys[k] === down) return !!k;
    keys[k] = down;
    send({ type: "move", keys });
    return true;
  }

  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (setKey(e.code, true)) e.preventDefault();
  });
  window.addEventListener("keyup", (e) => setKey(e.code, false));
  window.addEventListener("blur", () => {
    for (const k of Object.keys(keys)) keys[k] = false;
    send({ type: "move", keys });
    firing = false;
  });

  const canvas = $("canvas");
  window.addEventListener("mousemove", (e) => { mouse = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    mouse = { x: e.clientX, y: e.clientY };
    firing = true;
    tryShoot();
  });
  window.addEventListener("mouseup", (e) => { if (e.button === 0) firing = false; });
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  window.addEventListener("resize", () => Render.resize());

  // Holding the mouse button keeps firing at the cooldown rate; the server
  // enforces the real cooldown, the client just avoids spamming it.
  function tryShoot() {
    const now = performance.now();
    if (now - lastShotSent < hello.config.fire_cooldown * 1000 + 10) return;
    lastShotSent = now;
    send({ type: "shoot", angle: aimAngle });
  }

  $("join-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("name-input").value.trim();
    if (!name) return;
    $("join-error").textContent = "";
    saveSession({ name });
    sendJoin(name);
  });

  // ------------------------------------------------------------ render loop
  // Render one tick behind the newest snapshot, interpolating between the two
  // latest snapshots so movement looks smooth at 60fps with a 30Hz server.
  function lerpList(prev, curr, alpha, maxJump) {
    const before = new Map((prev || []).map((o) => [o.id, o]));
    return curr.map((o) => {
      const a = before.get(o.id);
      if (!a || a.x === undefined || o.x === undefined) return o;
      if (Math.hypot(o.x - a.x, o.y - a.y) > maxJump) return o; // respawn: don't slide across the map
      return { ...o, x: a.x + (o.x - a.x) * alpha, y: a.y + (o.y - a.y) * alpha };
    });
  }

  function frame() {
    requestAnimationFrame(frame);
    if (!snap || !hello || $("screen-game").classList.contains("hidden")) return;
    const now = performance.now();
    const interval = 1000 / hello.config.tick_rate;
    const alpha = Math.min(1, (now - snapTime) / interval);
    const players = lerpList(prevSnap && prevSnap.players, snap.players, alpha, 80);
    const bullets = lerpList(prevSnap && prevSnap.bullets, snap.bullets, alpha, 80);

    // Own aim is computed locally so the barrel follows the mouse instantly.
    const mine = me && players.find((p) => p.id === me.id);
    if (mine && mine.alive && mouse && snap.game_state === "RUNNING") {
      const m = Render.toWorld(mouse.x, mouse.y);
      aimAngle = Math.atan2(m.y - mine.y, m.x - mine.x);
      mine.angle = aimAngle;
      if (now - lastAimSent > 50 && aimAngle !== lastAimValue) {
        lastAimSent = now;
        lastAimValue = aimAngle;
        send({ type: "aim", angle: aimAngle });
      }
      if (firing) tryShoot();
    }

    $("hud-timer").textContent = fmtTime(liveTimeRemaining());
    $("waiting-timer").textContent = fmtTime(liveTimeRemaining());
    Render.draw({ players, bullets }, me && me.id, now);
  }

  connect();
  requestAnimationFrame(frame);
  setInterval(() => { // keep the waiting-screen timer ticking too
    if (snap && !$("screen-waiting").classList.contains("hidden")) $("waiting-timer").textContent = fmtTime(liveTimeRemaining());
  }, 250);
})();
