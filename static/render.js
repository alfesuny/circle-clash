// Canvas rendering. Everything is drawn in world coordinates and scaled to
// fit the window, so game logic never depends on screen size.
const Render = (() => {
  let canvas, ctx, map, cfg;
  let teamColor = {};
  let scale = 1;

  function init(canvasEl, gameMap, config, teams) {
    canvas = canvasEl;
    ctx = canvas.getContext("2d");
    map = gameMap;
    cfg = config;
    teamColor = Object.fromEntries(teams.map((t) => [t.id, t.color]));
    resize();
  }

  // Fit the world into the available area, keeping its aspect ratio.
  function resize() {
    if (!canvas) return;
    const wrap = canvas.parentElement.getBoundingClientRect();
    if (wrap.width === 0 || wrap.height === 0) return;
    scale = Math.min(wrap.width / map.width, wrap.height / map.height);
    const w = Math.floor(map.width * scale);
    const h = Math.floor(map.height * scale);
    const dpr = window.devicePixelRatio || 1;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    scale = w / map.width;
    ctx.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
  }

  function toWorld(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    return { x: (clientX - r.left) / scale, y: (clientY - r.top) / scale };
  }

  function hexToRgba(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  function drawBackground() {
    ctx.fillStyle = "#1a1d24";
    ctx.fillRect(0, 0, map.width, map.height);
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 50; x < map.width; x += 50) { ctx.moveTo(x, 0); ctx.lineTo(x, map.height); }
    for (let y = 50; y < map.height; y += 50) { ctx.moveTo(0, y); ctx.lineTo(map.width, y); }
    ctx.stroke();
  }

  function drawSpawnZones() {
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    for (const [team, z] of Object.entries(map.spawn_zones)) {
      const color = teamColor[team] || "#888888";
      ctx.fillStyle = hexToRgba(color, 0.12);
      ctx.fillRect(z.x, z.y, z.width, z.height);
      ctx.setLineDash([6, 6]);
      ctx.strokeStyle = hexToRgba(color, 0.6);
      ctx.lineWidth = 2;
      ctx.strokeRect(z.x, z.y, z.width, z.height);
      ctx.setLineDash([]);
      ctx.fillStyle = hexToRgba(color, 0.7);
      ctx.fillText(`${team.toUpperCase()} SPAWN`, z.x + z.width / 2, z.y + z.height / 2 + 4);
    }
  }

  function drawWalls() {
    ctx.fillStyle = "#4b5263";
    ctx.strokeStyle = "#626a7d";
    ctx.lineWidth = 2;
    for (const w of map.walls) {
      ctx.fillRect(w.x, w.y, w.width, w.height);
      ctx.strokeRect(w.x + 1, w.y + 1, w.width - 2, w.height - 2);
    }
  }

  function drawBullets(bullets) {
    for (const b of bullets) {
      ctx.fillStyle = teamColor[b.team] || "#fff";
      ctx.beginPath();
      ctx.arc(b.x, b.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.beginPath();
      ctx.arc(b.x, b.y, 2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function drawPlayer(p, isMe, now) {
    const r = cfg.player_radius;
    const color = teamColor[p.team] || "#888";

    // Flash while freshly respawned (invulnerable).
    ctx.globalAlpha = p.invulnerable ? (Math.floor(now / 120) % 2 ? 0.45 : 0.9) : 1;

    // gun barrel
    ctx.strokeStyle = "#d8dbe2";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x + Math.cos(p.angle) * (r + 9), p.y + Math.sin(p.angle) * (r + 9));
    ctx.stroke();

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = isMe ? 3 : 1.5;
    ctx.strokeStyle = isMe ? "#ffffff" : "rgba(0,0,0,0.5)";
    ctx.stroke();
    ctx.globalAlpha = 1;

    // shield ring when protected (spawn zone or post-respawn)
    if (p.protected) {
      ctx.strokeStyle = `rgba(180,220,255,${0.5 + 0.3 * Math.sin(now / 150)})`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r + 5, 0, Math.PI * 2);
      ctx.stroke();
    }

    // name
    ctx.font = `${isMe ? "bold " : ""}12px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.fillStyle = "#fff";
    ctx.fillText(p.name, p.x, p.y - r - 14);

    // health pips
    const max = cfg.player_health;
    const pip = 6, gap = 2;
    const total = max * pip + (max - 1) * gap;
    for (let i = 0; i < max; i++) {
      ctx.fillStyle = i < p.health ? "#ff5a5a" : "rgba(255,255,255,0.18)";
      ctx.fillRect(p.x - total / 2 + i * (pip + gap), p.y - r - 10, pip, 4);
    }
  }

  function draw(view, meId, now) {
    if (!ctx) return;
    drawBackground();
    drawSpawnZones();
    drawWalls();
    drawBullets(view.bullets);
    let me = null;
    for (const p of view.players) {
      if (!p.in_match || !p.alive || p.x === undefined) continue;
      if (p.id === meId) { me = p; continue; }
      drawPlayer(p, false, now);
    }
    if (me) drawPlayer(me, true, now); // own player on top
  }

  return { init, resize, toWorld, draw };
})();
