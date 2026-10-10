// Admin panel: logs in for a token, then polls /api/admin/status.
(() => {
  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "lanshooter-admin-token";
  let token = null;
  let durationTouched = false; // don't overwrite the inputs while the admin is editing them
  try { token = sessionStorage.getItem(TOKEN_KEY); } catch {}

  async function api(path, method = "GET", body) {
    const res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", "X-Admin-Token": token || "" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== "/api/admin/login") logout();
    if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
    return data;
  }

  function logout() {
    token = null;
    try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
    $("dash").classList.add("hidden");
    $("login").classList.remove("hidden");
  }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const data = await api("/api/admin/login", "POST", { password: $("password").value });
      token = data.token;
      try { sessionStorage.setItem(TOKEN_KEY, token); } catch {}
      $("login-error").textContent = "";
      showDash();
    } catch (err) {
      $("login-error").textContent = err.message;
    }
  });

  function showDash() {
    $("login").classList.add("hidden");
    $("dash").classList.remove("hidden");
    refresh();
  }

  function fmt(sec) {
    sec = Math.max(0, Math.ceil(sec));
    return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
  }

  function td(text, color) {
    const c = document.createElement("td");
    c.textContent = text;
    if (color) c.style.color = color;
    return c;
  }

  function render(s) {
    $("state").textContent = s.game_state;
    $("state").className = "state " + s.game_state;
    $("time").textContent = fmt(s.time_remaining);

    const teamColor = {}, teamName = {};
    const teams = $("teams");
    teams.innerHTML = "";
    let total = 0;
    for (const t of s.teams) {
      teamColor[t.id] = t.color;
      teamName[t.id] = t.name;
      total += t.count;
      const tr = document.createElement("tr");
      tr.append(td(t.name, t.color), td(`${t.count} / ${t.max}`), td(`${t.kills} kills`));
      teams.append(tr);
    }
    $("total").textContent = `${total} / ${s.teams.length * s.config.max_players_per_team}` +
      `  (${s.players.filter((p) => p.connected && !p.team).length} without a team)`;

    const players = $("players");
    players.innerHTML = "";
    for (const p of s.players) {
      const status = !p.connected ? "disconnected" : s.game_state !== "LOBBY" && !p.in_match ? "spectating" : "connected";
      const tr = document.createElement("tr");
      tr.append(td(p.name), td(p.team ? teamName[p.team] : "—", teamColor[p.team]), td(status),
        td(p.kills), td(p.deaths), td(p.score));
      players.append(tr);
    }

    if (!durationTouched && s.game_state !== "RUNNING") {
      $("minutes").value = Math.floor(s.duration / 60);
      $("seconds").value = s.duration % 60;
    }
    renderMaps(s);
    const running = s.game_state === "RUNNING";
    $("btn-start").disabled = running;
    $("btn-start").textContent = s.game_state === "ENDED" ? "START NEW GAME" : "START GAME";
    $("btn-end").disabled = !running;
    $("btn-lobby").disabled = s.game_state !== "ENDED";
    $("minutes").disabled = $("seconds").disabled = running;
  }

  function renderMaps(s) {
    const sel = $("map-select");
    const ids = s.maps.map((m) => m.id).join("|");
    if (sel.dataset.ids !== ids) {  // rebuild options only when the map list changes
      sel.dataset.ids = ids;
      sel.innerHTML = "";
      for (const m of s.maps) sel.append(new Option(m.name, m.id));
    }
    sel.value = s.map_id;
    sel.disabled = s.game_state === "RUNNING";
    const m = s.maps.find((x) => x.id === s.map_id);
    if (m && $("map-thumb").getAttribute("src") !== m.image_url) $("map-thumb").src = m.image_url;
  }

  $("map-select").addEventListener("change", (e) => action("/api/admin/map", { map_id: e.target.value }));

  async function refresh() {
    if (!token) return;
    try {
      render(await api("/api/admin/status"));
    } catch (err) {
      $("action-error").textContent = err.message;
    }
  }

  async function action(path, body) {
    $("action-error").textContent = "";
    try {
      await api(path, "POST", body);
      durationTouched = false;
    } catch (err) {
      $("action-error").textContent = err.message;
    }
    refresh();
  }

  for (const id of ["minutes", "seconds"]) $(id).addEventListener("input", () => { durationTouched = true; });

  $("btn-start").addEventListener("click", () => {
    const duration = (parseInt($("minutes").value, 10) || 0) * 60 + (parseInt($("seconds").value, 10) || 0);
    action("/api/admin/start", { duration });
  });
  $("btn-end").addEventListener("click", () => {
    if (confirm("End the match now?")) action("/api/admin/end");
  });
  $("btn-lobby").addEventListener("click", () => action("/api/admin/lobby"));

  if (token) showDash();
  setInterval(refresh, 1000);
})();
