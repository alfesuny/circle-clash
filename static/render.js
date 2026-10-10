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

  // Multiply a #rrggbb colour's channels by f (< 1 darker, > 1 lighter).
  function shade(hex, f) {
    const n = parseInt(hex.slice(1), 16);
    const c = (v) => Math.max(0, Math.min(255, Math.round(v * f)));
    return `rgb(${c((n >> 16) & 255)},${c((n >> 8) & 255)},${c(n & 255)})`;
  }

  function oval(x, y, rx, ry) {
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
  }

  function rrect(x, y, w, h, rad) {
    ctx.beginPath();
    ctx.moveTo(x + rad, y);
    ctx.arcTo(x + w, y, x + w, y + h, rad);
    ctx.arcTo(x + w, y + h, x, y + h, rad);
    ctx.arcTo(x, y + h, x, y, rad);
    ctx.arcTo(x, y, x + w, y, rad);
    ctx.closePath();
  }

  // Walk-cycle state per player. The distance actually walked drives the
  // stride, so legs move exactly as fast as the player and stop when they stop.
  const walk = {};

  function stride(p, r) {
    let w = walk[p.id];
    if (!w || Math.hypot(p.x - w.x, p.y - w.y) > 80) w = walk[p.id] = { x: p.x, y: p.y, dist: 0, moving: 0 };
    const step = Math.hypot(p.x - w.x, p.y - w.y);
    w.dist += step;
    w.x = p.x;
    w.y = p.y;
    w.moving += ((step > 0.05 ? 1 : 0) - w.moving) * 0.2; // ease in/out of the walk cycle
    return { phase: w.dist / (r * 0.5), moving: w.moving };
  }

  // A soldier standing upright (side-on), centred on the player's position.
  // Faces left/right with the aim and the rifle swivels to the exact aim
  // angle. The server's bullet hitbox is a capsule from head to feet
  // (player_radius wide, hitbox_half_height taller above and below).
  function drawSoldier(p, isMe, step) {
    const r = cfg.player_radius;
    const color = teamColor[p.team] || "#888888";
    const skin = "#e0b48a", boots = "#15171c";
    const left = Math.cos(p.angle) < 0;
    const aim = left ? Math.PI - p.angle : p.angle;              // aim after mirroring
    const swing = Math.sin(step.phase) * 0.6 * step.moving;      // leg angle (radians)
    const bob = -Math.abs(Math.sin(step.phase)) * r * 0.1 * step.moving;

    ctx.save();
    ctx.translate(p.x, p.y);
    if (left) ctx.scale(-1, 1);
    ctx.lineCap = "round";

    // shadow on the ground
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    oval(0, r * 1.52, r * 0.8, r * 0.2);
    ctx.fill();

    // legs: back leg darker, swinging opposite to the front one; boots point forward
    const hipY = r * 0.45 + bob, legLen = r;
    for (const [dir, f] of [[-1, 0.65], [1, 1]]) {
      const a = swing * dir;
      const fx = Math.sin(a) * legLen, fy = hipY + Math.cos(a) * legLen;
      ctx.strokeStyle = shade("#3b4252", f);
      ctx.lineWidth = r * 0.34;
      ctx.beginPath();
      ctx.moveTo(0, hipY);
      ctx.lineTo(fx, fy);
      ctx.stroke();
      ctx.fillStyle = boots;
      oval(fx + r * 0.12, fy + r * 0.03, r * 0.25, r * 0.13);
      ctx.fill();
    }

    // torso in team colour, with a belt
    const tTop = -r * 0.62 + bob, tW = r * 0.9, tH = r * 1.2;
    rrect(-tW / 2, tTop, tW, tH, r * 0.25);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = isMe ? 2 : 1;
    ctx.strokeStyle = isMe ? "#ffffff" : "rgba(0,0,0,0.55)";
    ctx.stroke();
    ctx.fillStyle = shade(color, 0.5);
    ctx.fillRect(-tW / 2, tTop + tH - r * 0.28, tW, r * 0.15);

    // head, eye on the facing side, helmet in a darker team colour
    const headY = tTop - r * 0.38;
    oval(0, headY, r * 0.4, r * 0.42);
    ctx.fillStyle = skin;
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(0,0,0,0.5)";
    ctx.stroke();
    ctx.fillStyle = "#1b1b1b";
    oval(r * 0.2, headY + r * 0.03, r * 0.06, r * 0.08);
    ctx.fill();
    ctx.fillStyle = shade(color, 0.6);
    ctx.beginPath();
    ctx.ellipse(0, headY - r * 0.05, r * 0.47, r * 0.42, 0, Math.PI, 0);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(-r * 0.4, headY - r * 0.1, r * 0.95, r * 0.1); // brim, longer at the front

    // rifle held in both hands, swivelling around the shoulder to the aim angle
    ctx.translate(r * 0.05, -r * 0.12 + bob);
    ctx.rotate(aim);
    // gunmetal grey with a dark outline so it reads against the dark map
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#0d0e11";
    ctx.fillStyle = "#6b7280";
    for (const [x, y, w, h] of [
      [r * 0.4, r * 0.1, r * 0.2, r * 0.32],     // magazine
      [r * 1.5, -r * 0.08, r * 0.65, r * 0.15],  // barrel
      [-r * 0.05, -r * 0.15, r * 1.55, r * 0.3], // body
    ]) {
      ctx.fillRect(x, y, w, h);
      ctx.strokeRect(x, y, w, h);
    }
    ctx.fillStyle = "#aab1bd";
    ctx.fillRect(r * 0.2, -r * 0.11, r * 1.1, r * 0.07);    // highlight
    ctx.strokeStyle = shade(color, 0.85);                    // sleeves
    ctx.lineWidth = r * 0.24;
    ctx.beginPath();
    ctx.moveTo(-r * 0.12, -r * 0.2);
    ctx.lineTo(r * 0.42, r * 0.12);
    ctx.moveTo(-r * 0.05, -r * 0.28);
    ctx.lineTo(r * 1.05, r * 0.06);
    ctx.stroke();
    ctx.fillStyle = skin;                                    // hands on the rifle
    for (const [hx, hy] of [[r * 0.42, r * 0.12], [r * 1.05, r * 0.06]]) {
      oval(hx, hy, r * 0.13, r * 0.13);
      ctx.fill();
    }

    ctx.restore();
  }

  function drawPlayer(p, isMe, now) {
    const r = cfg.player_radius;
    const step = stride(p, r);

    // Flash while freshly respawned (invulnerable).
    ctx.globalAlpha = p.invulnerable ? (Math.floor(now / 120) % 2 ? 0.45 : 0.9) : 1;
    drawSoldier(p, isMe, step);
    ctx.globalAlpha = 1;

    // shield bubble when protected (spawn zone or post-respawn)
    if (p.protected) {
      ctx.strokeStyle = `rgba(180,220,255,${0.5 + 0.3 * Math.sin(now / 150)})`;
      ctx.lineWidth = 2;
      oval(p.x, p.y, r * 1.25, r * 1.9);
      ctx.stroke();
    }

    // lives (hearts for everyone, so you can see who is nearly dead), name above
    const top = p.y - r * 1.55;
    const max = cfg.player_health;
    const size = isMe ? 10 : 8, gap = 2;
    const total = max * size + (max - 1) * gap;
    for (let i = 0; i < max; i++) {
      heart(p.x - total / 2 + size / 2 + i * (size + gap), top - 7, size, i < p.health);
    }
    ctx.font = `${isMe ? "bold " : ""}12px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(0,0,0,0.7)";
    ctx.strokeText(p.name, p.x, top - 15);
    ctx.fillStyle = "#fff";
    ctx.fillText(p.name, p.x, top - 15);
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
