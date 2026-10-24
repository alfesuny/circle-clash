// Canvas rendering. Everything is drawn in world coordinates through a camera
// that follows the local player, zoomed so the screen's shorter side shows
// camera_view_span world units. Game logic never depends on screen size.
const Render = (() => {
  const DEBUG = new URLSearchParams(location.search).has("debug"); // ?debug=1 shows collision rects
  let canvas, ctx, map = null, cfg;
  let teamColor = {};
  let scale = 1, dpr = 1;
  let viewW = 0, viewH = 0;   // canvas size in CSS pixels
  const cam = { x: 0, y: 0 }; // world point at the centre of the screen
  const images = {};          // image url -> HTMLImageElement
  let mini = null, mctx = null;           // minimap canvas (top left)
  let miniW = 0, miniH = 0, miniDpr = 1;  // its size in CSS pixels
  let miniBg = null, miniKey = null;      // offscreen: map, walls and spawns at minimap size

  function init(canvasEl, config, teams, minimapEl) {
    canvas = canvasEl;
    ctx = canvas.getContext("2d");
    mini = minimapEl;
    mctx = mini.getContext("2d");
    cfg = config;
    teamColor = Object.fromEntries(teams.map((t) => [t.id, t.color]));
  }

  function image(url) {
    if (!images[url]) {
      const img = new Image();
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

  // The canvas fills the window. The shorter side shows camera_view_span
  // world units and the longer one at most max_view_aspect times that (a very
  // wide window zooms in rather than seeing further). The server works out
  // the same view (Game.view_rect) to decide what to send.
  function resize() {
    if (!canvas || !map) return;
    const wrap = canvas.parentElement.getBoundingClientRect();
    if (wrap.width === 0 || wrap.height === 0) return;
    viewW = Math.floor(wrap.width);
    viewH = Math.floor(wrap.height);
    dpr = window.devicePixelRatio || 1;
    canvas.style.width = viewW + "px";
    canvas.style.height = viewH + "px";
    canvas.width = Math.floor(viewW * dpr);
    canvas.height = Math.floor(viewH * dpr);
    const span = cfg.camera_view_span;
    scale = Math.max(Math.min(viewW, viewH) / span, Math.max(viewW, viewH) / (span * cfg.max_view_aspect));
    setCamera(cam.x, cam.y);
    // minimap: the whole map, up to 220 px wide (less on small windows)
    miniW = Math.round(Math.min(220, viewW * 0.3));
    miniH = Math.round(miniW * map.height / map.width);
    miniDpr = dpr;
    mini.style.width = miniW + "px";
    mini.style.height = miniH + "px";
    mini.width = Math.floor(miniW * miniDpr);
    mini.height = Math.floor(miniH * miniDpr);
    miniKey = null;
  }

  // Centre the view on (x, y) without showing past the world's edges (on an
  // axis where the whole world fits on screen, centre the world instead).
  function setCamera(x, y) {
    if (!map || !viewW) return;
    const halfW = viewW / 2 / scale, halfH = viewH / 2 / scale;
    cam.x = map.width <= 2 * halfW ? map.width / 2 : Math.min(Math.max(x, halfW), map.width - halfW);
    cam.y = map.height <= 2 * halfH ? map.height / 2 : Math.min(Math.max(y, halfH), map.height - halfH);
  }

  function worldTransform(c) {
    c.setTransform(scale * dpr, 0, 0, scale * dpr, (viewW / 2 - cam.x * scale) * dpr, (viewH / 2 - cam.y * scale) * dpr);
  }

  function toWorld(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    return { x: (clientX - r.left - viewW / 2) / scale + cam.x, y: (clientY - r.top - viewH / 2) / scale + cam.y };
  }

  function hexToRgba(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  // Map art + spawn zones for map m, in world coordinates on context c.
  // line: spawn-zone outline width in world units.
  function paintMap(c, m, highlightTeam, line = Math.max(2, m.width / 400)) {
    if (imageReady(m)) {
      c.drawImage(image(m.image_url), 0, 0, m.width, m.height); // stretched to the world size
    } else {
      c.fillStyle = "#1a1d24";
      c.fillRect(0, 0, m.width, m.height);
    }
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

  // ------------------------------------------------------------ minimap
  // Map art dimmed, walls drawn solid so the corridors read at this size,
  // spawn zones (own one highlighted). Rebuilt when the map, team, size or
  // image readiness changes.
  function buildMiniBg(team) {
    miniBg = miniBg || document.createElement("canvas");
    miniBg.width = mini.width;
    miniBg.height = mini.height;
    const c = miniBg.getContext("2d");
    c.setTransform(mini.width / map.width, 0, 0, mini.height / map.height, 0, 0);
    paintMap(c, map, team, map.width / 150);
    c.fillStyle = "rgba(0,0,0,0.35)";
    c.fillRect(0, 0, map.width, map.height);
    c.fillStyle = "rgba(200,208,222,0.9)";
    for (const w of map.walls) c.fillRect(w.x, w.y, w.width, w.height);
  }

  // Dot for a player at minimap pixel (x, y). Enemies are diamonds, so they
  // read apart from teammates without relying on colour alone.
  function miniDot(x, y, color, enemy, isMe) {
    const r = isMe ? 4.5 : 3.5;
    mctx.beginPath();
    if (enemy) {
      mctx.moveTo(x, y - r - 1); mctx.lineTo(x + r + 1, y); mctx.lineTo(x, y + r + 1); mctx.lineTo(x - r - 1, y);
      mctx.closePath();
    } else {
      mctx.arc(x, y, r, 0, Math.PI * 2);
    }
    mctx.fillStyle = color;
    mctx.fill();
    mctx.lineWidth = isMe ? 2 : 1;
    mctx.strokeStyle = isMe ? "#ffffff" : "rgba(0,0,0,0.8)";
    mctx.stroke();
  }

  // The whole map with your screen's outline, you, your teammates and the
  // enemies your team can see (the server sends no other enemies).
  function drawMinimap(view, self) {
    if (!miniW) return;
    const team = self ? self.team : null;
    const key = `${map.id}|${team}|${mini.width}x${mini.height}|${imageReady(map)}`;
    if (key !== miniKey) {
      buildMiniBg(team);
      miniKey = key;
    }
    mctx.setTransform(1, 0, 0, 1, 0, 0);
    mctx.clearRect(0, 0, mini.width, mini.height);
    mctx.drawImage(miniBg, 0, 0);
    mctx.setTransform(miniDpr, 0, 0, miniDpr, 0, 0); // CSS pixels from here
    const kx = miniW / map.width, ky = miniH / map.height;
    const hw = viewW / 2 / scale, hh = viewH / 2 / scale;
    mctx.strokeStyle = "rgba(255,255,255,0.75)";
    mctx.lineWidth = 1;
    mctx.strokeRect((cam.x - hw) * kx + 0.5, (cam.y - hh) * ky + 0.5, 2 * hw * kx - 1, 2 * hh * ky - 1);
    for (const p of view.players) {
      if (!p.in_match || !p.alive || p.x === undefined || p === self) continue;
      miniDot(p.x * kx, p.y * ky, teamColor[p.team] || "#888888", p.team !== team, false);
    }
    if (self && self.alive && self.x !== undefined) miniDot(self.x * kx, self.y * ky, teamColor[self.team], false, true);
  }

  // The server sends teammates wherever they are and enemies/bullets only
  // while someone in the team has them on screen; the camera follows the
  // local player (see setCamera).
  function draw(view, meId, now) {
    if (!ctx || !map || !viewW) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#0c0d11";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    worldTransform(ctx);
    paintMap(ctx, map, null, 3 / scale);
    drawBullets(view.bullets);
    // skip soldiers that are off screen (teammates are sent from anywhere)
    const hw = viewW / 2 / scale + 60, hh = viewH / 2 / scale + 60;
    const self = view.players.find((p) => p.id === meId) || null;
    for (const p of view.players) {
      if (!p.in_match || !p.alive || p.x === undefined || p === self) continue;
      if (Math.abs(p.x - cam.x) > hw || Math.abs(p.y - cam.y) > hh) continue;
      drawPlayer(p, false, now);
    }
    if (self && self.in_match && self.alive && self.x !== undefined) drawPlayer(self, true, now); // own player on top
    drawMinimap(view, self);
  }

  return { init, setMap, resize, setCamera, toWorld, draw, drawPreview };
})();
