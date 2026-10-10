// Canvas rendering. Everything is drawn in world coordinates and scaled to
// fit the window, so game logic never depends on screen size.
const Render = (() => {
  const DEBUG = new URLSearchParams(location.search).has("debug"); // ?debug=1 shows collision rects
  let canvas, ctx, map = null, cfg;
  let teamColor = {};
  let scale = 1, dpr = 1;
  let bg = null;              // offscreen canvas: map image + spawn zones, pre-scaled to the screen
  const images = {};          // image url -> HTMLImageElement

  function init(canvasEl, config, teams) {
    canvas = canvasEl;
    ctx = canvas.getContext("2d");
    cfg = config;
    teamColor = Object.fromEntries(teams.map((t) => [t.id, t.color]));
  }

  function image(url) {
    if (!images[url]) {
      const img = new Image();
      img.onload = () => { if (map && map.image_url === url) buildBackground(); };
      img.src = url;
      images[url] = img;
    }
    return images[url];
  }

  function imageReady(m) {
    const img = image(m.image_url);
    return img.complete && img.naturalWidth > 0;
  }

  function setMap(m) {
    map = m;
    image(m.image_url);
    resize();
  }

  // Fit the world into the available area, keeping its aspect ratio.
  function resize() {
    if (!canvas || !map) return;
    const wrap = canvas.parentElement.getBoundingClientRect();
    if (wrap.width === 0 || wrap.height === 0) return;
    scale = Math.min(wrap.width / map.width, wrap.height / map.height);
    const w = Math.floor(map.width * scale);
    const h = Math.floor(map.height * scale);
    dpr = window.devicePixelRatio || 1;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    scale = w / map.width;
    buildBackground();
  }

  function toWorld(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    return { x: (clientX - r.left) / scale, y: (clientY - r.top) / scale };
  }

  function hexToRgba(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  // Map art + spawn zones for map m, in world coordinates on context c.
  function paintMap(c, m, highlightTeam) {
    if (imageReady(m)) {
      c.drawImage(image(m.image_url), 0, 0, m.width, m.height); // stretched to the world size
    } else {
      c.fillStyle = "#1a1d24";
      c.fillRect(0, 0, m.width, m.height);
    }
    const line = Math.max(2, m.width / 400);
    for (const [team, z] of Object.entries(m.spawn_zones)) {
      const color = teamColor[team] || "#888888";
      const mine = team === highlightTeam;
      c.fillStyle = hexToRgba(color, mine ? 0.3 : 0.16);
      c.fillRect(z.x, z.y, z.width, z.height);
      c.setLineDash([line * 3, line * 3]);
      c.strokeStyle = hexToRgba(color, mine ? 1 : 0.6);
      c.lineWidth = mine ? line * 1.5 : line;
      c.strokeRect(z.x, z.y, z.width, z.height);
      c.setLineDash([]);
    }
    if (DEBUG || !imageReady(m)) {
      c.fillStyle = DEBUG ? "rgba(255,0,255,0.45)" : "#4b5263";
      for (const w of m.walls) c.fillRect(w.x, w.y, w.width, w.height);
    }
  }

  function buildBackground() {
    if (!canvas || !map) return;
    bg = bg || document.createElement("canvas");
    bg.width = canvas.width;
    bg.height = canvas.height;
    const b = bg.getContext("2d");
    b.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
    paintMap(b, map, null);
  }

  // Small preview of map m into a <canvas>, highlighting team's spawn.
  function drawPreview(el, m, team) {
    const width = el.clientWidth || 360;
    const height = Math.round(width * m.height / m.width);
    const d = window.devicePixelRatio || 1;
    el.style.height = height + "px";
    el.width = Math.floor(width * d);
    el.height = Math.floor(height * d);
    const c = el.getContext("2d");
    c.setTransform(width * d / m.width, 0, 0, height * d / m.height, 0, 0);
    paintMap(c, m, team);
    return imageReady(m);
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

  function heart(x, y, size, filled) {
    // two circles + a triangle; (x, y) is the centre
    const s = size / 2;
    ctx.beginPath();
    ctx.moveTo(x, y + s);
    ctx.bezierCurveTo(x - s * 1.6, y - s * 0.2, x - s * 0.7, y - s * 1.3, x, y - s * 0.45);
    ctx.bezierCurveTo(x + s * 0.7, y - s * 1.3, x + s * 1.6, y - s * 0.2, x, y + s);
    ctx.closePath();
    ctx.fillStyle = filled ? "#ff4d5e" : "rgba(255,255,255,0.18)";
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(0,0,0,0.6)";
    ctx.stroke();
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
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(0,0,0,0.7)";
    ctx.strokeText(p.name, p.x, p.y - r - 16);
    ctx.fillStyle = "#fff";
    ctx.fillText(p.name, p.x, p.y - r - 16);

    // lives: hearts for everyone, so you can see who is nearly dead
    const max = cfg.player_health;
    const size = isMe ? 10 : 8, gap = 2;
    const total = max * size + (max - 1) * gap;
    for (let i = 0; i < max; i++) {
      heart(p.x - total / 2 + size / 2 + i * (size + gap), p.y - r - 8, size, i < p.health);
    }
  }

  function draw(view, meId, now) {
    if (!ctx || !map) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (bg) ctx.drawImage(bg, 0, 0);
    ctx.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
    drawBullets(view.bullets);
    let me = null;
    for (const p of view.players) {
      if (!p.in_match || !p.alive || p.x === undefined) continue;
      if (p.id === meId) { me = p; continue; }
      drawPlayer(p, false, now);
    }
    if (me) drawPlayer(me, true, now); // own player on top
  }

  return { init, setMap, resize, toWorld, draw, drawPreview };
})();
