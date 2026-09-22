(() => {
  "use strict";

  const GAME_CONFIG = {
    rescue: {
      activity: "rescue-world", title: "Little Heroes Rescue World", short: "Rescue World",
      eyebrow: "Adventure mission", instruction: "Explore the world, collect every power star, then reach your teammate.", controls: "move"
    },
    kart: {
      activity: "kart-racing", title: "Character Kart Racing", short: "Kart Racing",
      eyebrow: "Championship race", instruction: "Steer around hazards, collect turbo stars and race all the way to the finish.", controls: "drive"
    },
    runner: {
      activity: "rescue-runner", title: "Endless Rescue Runner", short: "Rescue Runner",
      eyebrow: "Action mission", instruction: "Jump over obstacles, dash through barriers and collect sparkling gems.", controls: "runner"
    },
    academy: {
      activity: "training-academy", title: "Superhero Training Academy", short: "Training Academy",
      eyebrow: "Three-part training", instruction: "Master target practice, the obstacle track and the flying-ring challenge.", controls: "tap"
    },
    cafe: {
      activity: "pet-cafe", title: "Pet Café Adventure", short: "Pet Café",
      eyebrow: "Café shift", instruction: "Remember each customer's order, prepare every item and serve five happy guests.", controls: "food"
    },
    dance: {
      activity: "dance-party", title: "Character Dance Party", short: "Dance Party",
      eyebrow: "Rhythm show", instruction: "Tap the matching move as it reaches the glowing beat line and build a combo.", controls: "dance"
    },
    hide: {
      activity: "hide-and-seek", title: "Hide & Seek World", short: "Hide & Seek",
      eyebrow: "Big world search", instruction: "Explore the whole scene and find every hidden friend and special object.", controls: "search"
    }
  };

  const query = new URLSearchParams(location.search);
  const requestedKey = query.get("game") || "rescue";
  const gameKey = GAME_CONFIG[requestedKey] ? requestedKey : "rescue";
  const config = GAME_CONFIG[gameKey];
  const byId = id => document.getElementById(id);
  const canvas = byId("gameCanvas");
  const ctx = canvas.getContext("2d");
  const frame = byId("gameFrame");
  const overlay = byId("gameOverlay");
  const overlayCard = byId("overlayCard");
  const controls = byId("touchControls");
  const input = { left: false, right: false, up: false, down: false, action: false, alt: false };
  const images = [];
  let plan = null;
  let attempt = 0;
  let game = null;
  let running = false;
  let paused = false;
  let completed = false;
  let lastFrame = performance.now();
  let elapsed = 0;
  let audioEnabled = localStorage.getItem("littleLearnersGameSound") !== "off";
  let audioContext = null;
  let pointerStart = null;
  let pointerMoved = false;

  document.title = config.title + " | Little Learners";
  document.body.dataset.progressActivity = config.activity;
  byId("gameTitle").textContent = config.title;
  byId("soundButton").textContent = audioEnabled ? "🔊" : "🔇";

  const api = async (path, options = {}) => {
    const response = await fetch(ProfileShell.url(path), {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...options
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "The game could not load. Please try again.");
    return data;
  };

  function seededRandom(seed) {
    let value = Number(seed) >>> 0;
    return () => {
      value += 0x6D2B79F5;
      let result = value;
      result = Math.imul(result ^ result >>> 15, result | 1);
      result ^= result + Math.imul(result ^ result >>> 7, result | 61);
      return ((result ^ result >>> 14) >>> 0) / 4294967296;
    };
  }

  const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const choose = (random, list) => list[Math.floor(random() * list.length) % list.length];
  const shuffle = (random, list) => {
    const copy = [...list];
    for (let index = copy.length - 1; index > 0; index -= 1) {
      const target = Math.floor(random() * (index + 1));
      [copy[index], copy[target]] = [copy[target], copy[index]];
    }
    return copy;
  };

  function unlockAudio() {
    if (!audioEnabled) return;
    audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === "suspended") audioContext.resume().catch(() => {});
  }

  function tone(frequency = 440, duration = .1, type = "sine", volume = .05, slide = 0) {
    if (!audioEnabled) return;
    unlockAudio();
    if (!audioContext) return;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, audioContext.currentTime);
    if (slide) oscillator.frequency.exponentialRampToValueAtTime(Math.max(40, frequency + slide), audioContext.currentTime + duration);
    gain.gain.setValueAtTime(volume, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, audioContext.currentTime + duration);
    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + duration);
  }

  function sound(name) {
    if (name === "collect") { tone(660, .09, "triangle", .06, 180); setTimeout(() => tone(900, .08, "triangle", .045), 65); }
    else if (name === "bump") tone(150, .18, "sawtooth", .045, -55);
    else if (name === "jump") tone(260, .15, "square", .035, 310);
    else if (name === "correct") { tone(520, .1, "triangle", .05, 130); setTimeout(() => tone(760, .13, "triangle", .05, 180), 90); }
    else if (name === "wrong") tone(190, .2, "square", .035, -60);
    else if (name === "win") [523, 659, 784, 1047].forEach((note, index) => setTimeout(() => tone(note, .23, "triangle", .055), index * 110));
    else if (name === "beat") tone(180, .045, "sine", .025);
  }

  function roundedRect(context, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    context.beginPath();
    context.roundRect ? context.roundRect(x, y, width, height, r) : context.rect(x, y, width, height);
  }

  const WORLD_PALETTES = {
    "Rainbow City": ["#68d6ff", "#bcefff", "#8a72eb", "#52c989"],
    "Sunny Farm": ["#62cdf4", "#d8f5ff", "#efb348", "#74ca68"],
    "Pirate Island": ["#45c4e5", "#c8f7ff", "#c59752", "#35a992"],
    "Snowy Mountain": ["#8abff5", "#eaf8ff", "#a9b7d9", "#e8f4ff"],
    "Moon Base": ["#24265d", "#5e5b9d", "#7d78b8", "#40517e"],
    "Magic Forest": ["#62ceb4", "#d9f8d3", "#6f4baa", "#3d9d67"],
    "Coral Bay": ["#45cde5", "#d7fbff", "#ff8d83", "#51b9a2"],
    "School Adventure": ["#69cef2", "#eaf8ff", "#ed8a55", "#67bd72"]
  };

  function drawBackdrop(offset = 0, groundLine = 505) {
    const palette = WORLD_PALETTES[plan?.world] || WORLD_PALETTES["Rainbow City"];
    const sky = ctx.createLinearGradient(0, 0, 0, groundLine);
    sky.addColorStop(0, palette[0]);
    sky.addColorStop(1, palette[1]);
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, 1280, 720);
    const moon = plan?.world === "Moon Base";
    ctx.fillStyle = moon ? "#f2ecb0" : "#fff4a5";
    ctx.shadowColor = ctx.fillStyle;
    ctx.shadowBlur = 35;
    ctx.beginPath(); ctx.arc(1070, 105, 55, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
    for (let index = 0; index < 7; index += 1) {
      const x = ((index * 245 - offset * .18) % 1650 + 1650) % 1650 - 120;
      const y = 150 + (index % 3) * 58;
      ctx.fillStyle = moon ? "#ffffff1d" : "#ffffffa8";
      ctx.beginPath();
      ctx.arc(x, y, 33, 0, Math.PI * 2); ctx.arc(x + 38, y - 12, 45, 0, Math.PI * 2); ctx.arc(x + 83, y + 2, 31, 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = palette[2];
    ctx.beginPath(); ctx.moveTo(0, groundLine);
    for (let x = 0; x <= 1280; x += 120) ctx.lineTo(x, groundLine - 90 - Math.sin((x + offset * .09) / 160) * 75);
    ctx.lineTo(1280, groundLine); ctx.closePath(); ctx.fill();
    ctx.fillStyle = palette[3];
    ctx.fillRect(0, groundLine - 5, 1280, 725 - groundLine);
    for (let index = 0; index < 22; index += 1) {
      const x = ((index * 89 - offset * .45) % 1450 + 1450) % 1450 - 80;
      ctx.fillStyle = index % 2 ? "#ffffff20" : "#173e5930";
      ctx.beginPath(); ctx.ellipse(x, groundLine + 55 + (index % 5) * 32, 35, 12, -.2, 0, Math.PI * 2); ctx.fill();
    }
  }

  function drawCharacter(image, x, y, size, options = {}) {
    const { flip = false, bob = 0, glow = "#ffffff", alpha = 1, ring = false } = options;
    const drawY = y + bob;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(x, drawY);
    if (flip) ctx.scale(-1, 1);
    ctx.shadowColor = "#14223e66";
    ctx.shadowBlur = 12;
    ctx.shadowOffsetY = 9;
    if (ring) {
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(0, 0, size * .52, 0, Math.PI * 2); ctx.fill();
    }
    if (image?.complete && image.naturalWidth) ctx.drawImage(image, -size / 2, -size / 2, size, size);
    else {
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(0, 0, size * .42, 0, Math.PI * 2); ctx.fill();
      ctx.font = size * .5 + "px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("🦸", 0, 0);
    }
    ctx.restore();
  }

  function drawSparkle(x, y, scale = 1, colour = "#ffd330") {
    ctx.save(); ctx.translate(x, y); ctx.scale(scale, scale); ctx.fillStyle = colour; ctx.shadowColor = colour; ctx.shadowBlur = 16;
    ctx.beginPath();
    for (let index = 0; index < 10; index += 1) {
      const radius = index % 2 ? 8 : 23;
      const angle = -Math.PI / 2 + index * Math.PI / 5;
      ctx.lineTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
    }
    ctx.closePath(); ctx.fill(); ctx.restore();
  }

  function setHud(score, scoreLabel, time, timeLabel, objective) {
    byId("hud").hidden = false;
    byId("objectiveBar").hidden = false;
    byId("hudScore").textContent = score;
    byId("hudScoreLabel").textContent = scoreLabel;
    byId("hudTime").textContent = time;
    byId("hudTimeLabel").textContent = timeLabel;
    byId("objectiveBar").textContent = objective;
  }

  function toast(message) {
    const element = byId("gameToast");
    element.textContent = message;
    element.classList.remove("show");
    void element.offsetWidth;
    element.classList.add("show");
  }

  function confetti() {
    const symbols = ["⭐", "✨", "●", "◆", "★"];
    for (let index = 0; index < 42; index += 1) {
      const piece = document.createElement("i");
      piece.className = "confetti-piece";
      piece.textContent = symbols[index % symbols.length];
      piece.style.left = Math.random() * 100 + "%";
      piece.style.color = ["#ffdb35", "#ff5787", "#54d8ed", "#71dd8c", "#aa75f5"][index % 5];
      piece.style.setProperty("--drift", (Math.random() * 300 - 150) + "px");
      piece.style.animationDelay = Math.random() * .5 + "s";
      frame.appendChild(piece);
      setTimeout(() => piece.remove(), 2900);
    }
  }

  function clearInput() {
    Object.keys(input).forEach(key => { input[key] = false; });
    controls.querySelectorAll(".active").forEach(button => button.classList.remove("active"));
  }

  function bindHoldButton(button) {
    const key = button.dataset.input;
    const down = event => { unlockAudio(); input[key] = true; button.classList.add("active"); event.preventDefault(); };
    const up = event => { input[key] = false; button.classList.remove("active"); event?.preventDefault(); };
    button.addEventListener("pointerdown", down);
    button.addEventListener("pointerup", up);
    button.addEventListener("pointercancel", up);
    button.addEventListener("pointerleave", up);
  }

  function movementMarkup(vertical = true) {
    return `<div class="move-pad">
      ${vertical ? '<button class="control-button move-up" data-input="up" type="button" aria-label="Move up">▲</button>' : ""}
      <button class="control-button move-left" data-input="left" type="button" aria-label="Move left">◀</button>
      ${vertical ? '<button class="control-button move-down" data-input="down" type="button" aria-label="Move down">▼</button>' : ""}
      <button class="control-button move-right" data-input="right" type="button" aria-label="Move right">▶</button>
    </div>`;
  }

  function setControls(type) {
    clearInput();
    if (type === "move") controls.innerHTML = movementMarkup(true) + '<div class="tap-instruction">Explore the whole world</div><div class="action-pad"><button class="control-button action-button" data-input="action" type="button">POWER</button></div>';
    else if (type === "drive") controls.innerHTML = movementMarkup(false) + '<div class="tap-instruction">Steer and use turbo</div><div class="action-pad"><button class="control-button action-button" data-input="action" type="button">TURBO</button></div>';
    else if (type === "runner") controls.innerHTML = '<div class="tap-instruction">Jump over obstacles and dash through glowing barriers</div><div class="action-pad"><button class="control-button action-button alt" data-input="alt" type="button">DASH</button><button class="control-button action-button" data-input="action" type="button">JUMP</button></div>';
    else if (type === "flight") controls.innerHTML = movementMarkup(true) + '<div class="tap-instruction">Fly through every ring</div><div class="action-pad"><button class="control-button action-button" data-input="action" type="button">BOOST</button></div>';
    else if (type === "tap") controls.innerHTML = '<div class="tap-instruction">Tap the glowing targets inside the game</div>';
    else if (type === "search") controls.innerHTML = movementMarkup(false) + '<div class="tap-instruction">Drag the world or use the arrows, then tap what you find</div><div class="action-pad"><button class="control-button action-button alt" data-input="action" type="button">HINT</button></div>';
    else controls.innerHTML = "";
    controls.querySelectorAll("[data-input]").forEach(bindHoldButton);
  }

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / rect.width * 1280, y: (event.clientY - rect.top) / rect.height * 720 };
  }

  function imagePromise(source) {
    return new Promise(resolve => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => resolve(image);
      image.src = ProfileShell.url(source);
    });
  }

  function rescueGame() {
    const random = seededRandom(plan.seed);
    const hero = { x: 112, y: 570, radius: 44 };
    const teammate = { x: 1145, y: 158 };
    const stars = [];
    const obstacles = [];
    for (let index = 0; index < 13; index += 1) {
      obstacles.push({ x: 175 + random() * 890, y: 175 + random() * 385, radius: 32 + random() * 28, kind: choose(random, ["tree", "rock", "bush"]) });
    }
    while (stars.length < 7) {
      const candidate = { x: 125 + random() * 1030, y: 135 + random() * 460, collected: false };
      if (distance(candidate, hero) > 150 && distance(candidate, teammate) > 100 && obstacles.every(obstacle => distance(candidate, obstacle) > obstacle.radius + 45)) stars.push(candidate);
    }
    let collected = 0;
    let powerFlash = 0;
    return {
      update(dt) {
        let x = Number(input.right) - Number(input.left);
        let y = Number(input.down) - Number(input.up);
        const length = Math.hypot(x, y) || 1;
        const speed = input.action ? 370 : 275;
        x = x / length * speed * dt; y = y / length * speed * dt;
        const old = { x: hero.x, y: hero.y };
        hero.x = clamp(hero.x + x, 58, 1222); hero.y = clamp(hero.y + y, 105, 655);
        if (obstacles.some(obstacle => distance(hero, obstacle) < hero.radius + obstacle.radius * .76)) { hero.x = old.x; hero.y = old.y; }
        for (const star of stars) {
          if (!star.collected && distance(hero, star) < 63) {
            star.collected = true; collected += 1; powerFlash = .35; sound("collect"); toast(collected === stars.length ? "Portal unlocked! Find your teammate!" : "Power star " + collected + " of " + stars.length);
          }
        }
        powerFlash = Math.max(0, powerFlash - dt);
        setHud(collected + "/" + stars.length, "Power stars", "Mission " + plan.mission_number, plan.world, collected === stars.length ? "Reach your teammate at the glowing portal!" : "Explore and collect every power star");
        if (collected === stars.length && distance(hero, teammate) < 92) finishGame(3, collected * 250, "Rescue complete! Your team saved the day.");
      },
      draw() {
        drawBackdrop(0, 116);
        ctx.fillStyle = "#61bd72"; ctx.fillRect(0, 116, 1280, 604);
        ctx.strokeStyle = "#ffffff32"; ctx.lineWidth = 4;
        for (let x = 0; x < 1280; x += 105) { ctx.beginPath(); ctx.moveTo(x, 116); ctx.lineTo(x - 200, 720); ctx.stroke(); }
        for (let y = 150; y < 720; y += 95) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(1280, y); ctx.stroke(); }
        ctx.fillStyle = "#efcf7e"; roundedRect(ctx, 55, 520, 1160, 108, 54); ctx.fill();
        obstacles.sort((a, b) => a.y - b.y).forEach(obstacle => {
          ctx.save(); ctx.translate(obstacle.x, obstacle.y);
          ctx.fillStyle = "#17375d35"; ctx.beginPath(); ctx.ellipse(0, obstacle.radius * .62, obstacle.radius, obstacle.radius * .3, 0, 0, Math.PI * 2); ctx.fill();
          if (obstacle.kind === "tree") { ctx.fillStyle = "#8b572a"; ctx.fillRect(-10, -2, 20, obstacle.radius * 1.1); ctx.fillStyle = "#238a52"; ctx.beginPath(); ctx.arc(0, -8, obstacle.radius, 0, Math.PI * 2); ctx.fill(); }
          else { ctx.fillStyle = obstacle.kind === "rock" ? "#71839b" : "#258f58"; ctx.beginPath(); ctx.arc(0, 6, obstacle.radius, 0, Math.PI * 2); ctx.fill(); }
          ctx.restore();
        });
        stars.forEach((star, index) => { if (!star.collected) drawSparkle(star.x, star.y + Math.sin(elapsed * 3 + index) * 9, .9 + Math.sin(elapsed * 4 + index) * .08); });
        if (collected === stars.length) {
          const pulse = 1 + Math.sin(elapsed * 5) * .1;
          ctx.strokeStyle = "#fff27a"; ctx.lineWidth = 14; ctx.shadowColor = "#fff27a"; ctx.shadowBlur = 24;
          ctx.beginPath(); ctx.arc(teammate.x, teammate.y, 72 * pulse, 0, Math.PI * 2); ctx.stroke(); ctx.shadowBlur = 0;
        }
        drawCharacter(images[1], teammate.x, teammate.y, 112, { bob: Math.sin(elapsed * 3) * 5, ring: collected === stars.length, glow: "#fff4a5" });
        drawCharacter(images[0], hero.x, hero.y, 105 + powerFlash * 35, { flip: xDirection() < 0, bob: Math.sin(elapsed * 8) * 2 });
      }
    };
  }

  function xDirection() { return input.left ? -1 : input.right ? 1 : 0; }

  function kartGame() {
    const random = seededRandom(plan.seed);
    const objects = [];
    let playerX = 0;
    let distanceTravelled = 0;
    let stars = 0;
    let bumps = 0;
    let turbo = 0;
    let spawnTimer = 0;
    let wobble = 0;
    const finishDistance = 1500;
    function spawnRow() {
      const lanes = shuffle(random, [-1, 0, 1]);
      const safeStar = random() > .24;
      objects.push({ lane: lanes[0], z: 0, kind: safeStar ? "star" : "cone", hit: false });
      if (random() > .28) objects.push({ lane: lanes[1], z: -.04, kind: safeStar ? "cone" : "star", hit: false });
    }
    return {
      update(dt) {
        const steer = Number(input.right) - Number(input.left);
        playerX = clamp(playerX + steer * dt * 1.8, -1.12, 1.12);
        if (input.action && turbo > 0) turbo = Math.max(0, turbo - dt * .32);
        const speed = input.action && turbo > 0 ? 1.45 : 1;
        distanceTravelled += dt * 42 * speed;
        spawnTimer -= dt * speed;
        if (spawnTimer <= 0 && distanceTravelled < finishDistance - 100) { spawnRow(); spawnTimer = .72 + random() * .38; }
        for (const object of objects) {
          object.z += dt * (.36 + speed * .17);
          if (!object.hit && object.z > .84 && object.z < 1.08 && Math.abs(object.lane - playerX) < .43) {
            object.hit = true;
            if (object.kind === "star") { stars += 1; turbo = clamp(turbo + .22, 0, 1); sound("collect"); }
            else { bumps += 1; wobble = .45; sound("bump"); }
          }
        }
        while (objects.length && objects[0].z > 1.25) objects.shift();
        wobble = Math.max(0, wobble - dt);
        const metres = Math.min(finishDistance, Math.floor(distanceTravelled));
        setHud(stars, "Turbo stars", metres + "m", "of " + finishDistance + "m", turbo > .12 ? "Hold TURBO for a speed boost!" : "Steer around hazards and collect turbo stars");
        if (distanceTravelled >= finishDistance) finishGame(stars >= 12 ? 3 : stars >= 7 ? 2 : 1, stars * 300 - bumps * 40 + 1500, "Finish line crossed! What a race!");
      },
      draw() {
        drawBackdrop(distanceTravelled * 9, 355);
        const horizon = 260;
        ctx.fillStyle = "#51576d";
        ctx.beginPath(); ctx.moveTo(500, horizon); ctx.lineTo(780, horizon); ctx.lineTo(1160, 720); ctx.lineTo(120, 720); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = "#f6e56d"; ctx.lineWidth = 9; ctx.setLineDash([45, 36]); ctx.lineDashOffset = distanceTravelled * 4;
        for (const offset of [-.33, .33]) { ctx.beginPath(); ctx.moveTo(640 + offset * 260, horizon); ctx.lineTo(640 + offset * 960, 720); ctx.stroke(); }
        ctx.setLineDash([]);
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 12;
        ctx.beginPath(); ctx.moveTo(500, horizon); ctx.lineTo(120, 720); ctx.stroke(); ctx.beginPath(); ctx.moveTo(780, horizon); ctx.lineTo(1160, 720); ctx.stroke();
        const ordered = [...objects].sort((a, b) => a.z - b.z);
        for (const object of ordered) {
          if (object.hit) continue;
          const z = clamp(object.z, 0, 1.18), y = horizon + z * z * (720 - horizon), half = 140 + z * 380;
          const x = 640 + object.lane * half * .58;
          const scale = .25 + z * 1.16;
          if (object.kind === "star") drawSparkle(x, y - 30 * scale, scale, "#ffe344");
          else { ctx.font = 55 * scale + "px system-ui"; ctx.textAlign = "center"; ctx.fillText("🚧", x, y); }
        }
        const kartX = 640 + playerX * 355;
        ctx.save(); ctx.translate(kartX, 602); if (wobble) ctx.rotate(Math.sin(elapsed * 35) * wobble * .18);
        ctx.fillStyle = input.action && turbo > 0 ? "#58e6ff" : "#ff5b72"; ctx.shadowColor = "#111a3e88"; ctx.shadowBlur = 16;
        roundedRect(ctx, -82, -35, 164, 86, 32); ctx.fill();
        ctx.fillStyle = "#171d37"; ctx.beginPath(); ctx.arc(-62, 48, 23, 0, Math.PI * 2); ctx.arc(62, 48, 23, 0, Math.PI * 2); ctx.fill();
        drawCharacter(images[0], 0, -70, 112, { bob: Math.sin(elapsed * 12) * 2 }); ctx.restore();
        ctx.fillStyle = "#ffffff35"; roundedRect(ctx, 1040, 75, 170, 24, 12); ctx.fill();
        ctx.fillStyle = "#55ddf4"; roundedRect(ctx, 1040, 75, 170 * turbo, 24, 12); ctx.fill();
      }
    };
  }

  function runnerGame() {
    const random = seededRandom(plan.seed);
    const ground = 574;
    const player = { x: 225, y: ground, velocity: 0, onGround: true };
    const objects = [];
    let distanceRun = 0;
    let gems = 0;
    let hits = 0;
    let spawnTimer = .8;
    let jumpLatch = false;
    let dash = 0;
    const finishDistance = 1250;
    function spawn() {
      const isGem = random() > .42;
      objects.push({ x: 1380, y: isGem ? ground - 85 - random() * 105 : ground, kind: isGem ? "gem" : choose(random, ["log", "barrier"]), used: false });
      if (isGem && random() > .45) objects.push({ x: 1460, y: ground - 140, kind: "gem", used: false });
    }
    return {
      update(dt) {
        if (input.action && !jumpLatch && player.onGround) { player.velocity = -720; player.onGround = false; jumpLatch = true; sound("jump"); }
        if (!input.action) jumpLatch = false;
        dash = input.alt ? Math.min(1, dash + dt * 5) : Math.max(0, dash - dt * 4);
        player.velocity += 1680 * dt; player.y += player.velocity * dt;
        if (player.y >= ground) { player.y = ground; player.velocity = 0; player.onGround = true; }
        const speed = 330 + dash * 150;
        distanceRun += dt * speed * .1;
        spawnTimer -= dt;
        if (spawnTimer <= 0 && distanceRun < finishDistance - 80) { spawn(); spawnTimer = .72 + random() * .65; }
        for (const object of objects) {
          object.x -= speed * dt;
          if (object.used) continue;
          const dx = Math.abs(object.x - player.x), dy = Math.abs(object.y - player.y);
          if (object.kind === "gem" && dx < 60 && dy < 85) { object.used = true; gems += 1; sound("collect"); }
          if (object.kind !== "gem" && dx < 62 && player.y > ground - 88) {
            object.used = true;
            if (object.kind === "barrier" && dash > .45) { gems += 1; sound("collect"); toast("Power dash!"); }
            else { hits += 1; sound("bump"); toast("Keep going!"); }
          }
        }
        while (objects.length && objects[0].x < -120) objects.shift();
        setHud(gems, "Sparkling gems", Math.min(finishDistance, Math.floor(distanceRun)) + "m", "of " + finishDistance + "m", "JUMP over logs • DASH through glowing barriers");
        if (distanceRun >= finishDistance) finishGame(gems >= 15 ? 3 : gems >= 8 ? 2 : 1, gems * 250 - hits * 30 + 1200, "Route complete! Your teammate made it safely.");
      },
      draw() {
        drawBackdrop(distanceRun * 10, 500);
        ctx.fillStyle = "#e8ca79"; ctx.fillRect(0, ground + 45, 1280, 101);
        ctx.fillStyle = "#ffffff46";
        for (let index = 0; index < 14; index += 1) { const x = ((index * 120 - distanceRun * 8) % 1700 + 1700) % 1700 - 130; ctx.fillRect(x, ground + 82, 68, 10); }
        for (const object of objects) {
          if (object.used) continue;
          if (object.kind === "gem") { ctx.save(); ctx.translate(object.x, object.y); ctx.rotate(Math.PI / 4 + elapsed); ctx.fillStyle = "#55e8ff"; ctx.shadowColor = "#55e8ff"; ctx.shadowBlur = 20; ctx.fillRect(-20, -20, 40, 40); ctx.restore(); }
          else { ctx.font = object.kind === "log" ? "75px system-ui" : "82px system-ui"; ctx.textAlign = "center"; ctx.fillText(object.kind === "log" ? "🪵" : "⚡", object.x, ground + 35); }
        }
        if (dash > .15) { ctx.strokeStyle = "#6deaff88"; ctx.lineWidth = 10; for (let line = 0; line < 4; line += 1) { ctx.beginPath(); ctx.moveTo(player.x - 130 - line * 30, player.y - 60 + line * 25); ctx.lineTo(player.x - 50, player.y - 60 + line * 25); ctx.stroke(); } }
        drawCharacter(images[0], player.x, player.y - 62, 128, { bob: player.onGround ? Math.sin(elapsed * 14) * 5 : 0 });
        drawCharacter(images[1], 1090, 176, 115, { bob: Math.sin(elapsed * 4) * 7, ring: true, glow: "#dff9ff" });
      }
    };
  }

  function academyGame() {
    const random = seededRandom(plan.seed);
    let phase = "targets";
    let phaseScore = 0;
    let totalScore = 0;
    let targetHits = 0;
    let targets = Array.from({ length: 7 }, (_, index) => ({
      x: 180 + random() * 920, y: 150 + random() * 380,
      vx: (random() > .5 ? 1 : -1) * (45 + random() * 55), vy: (random() > .5 ? 1 : -1) * (30 + random() * 45),
      radius: 42 + random() * 16, hit: false, symbol: ["⭐", "⚡", "💎"][index % 3]
    }));
    const athlete = { x: 230, y: 574, velocity: 0, onGround: true };
    let obstacles = [];
    let obstacleTimer = .8;
    let obstaclesSpawned = 0;
    let obstaclesPassed = 0;
    let obstacleHits = 0;
    let jumpLatch = false;
    const flyer = { x: 225, y: 350 };
    let rings = [];
    let ringTimer = .5;
    let ringsPassed = 0;
    let ringsMissed = 0;
    function nextPhase(next) {
      phase = next; sound("correct");
      if (next === "obstacles") { toast("Challenge 2: Obstacle track!"); setControls("runner"); }
      if (next === "flight") { toast("Final challenge: Flying rings!"); setControls("flight"); }
    }
    return {
      start() { setControls("tap"); },
      handleTap(x, y) {
        if (phase !== "targets") return;
        const target = targets.find(item => !item.hit && Math.hypot(item.x - x, item.y - y) < item.radius + 22);
        if (!target) { sound("wrong"); toast("Nearly! Tap a glowing target."); return; }
        target.hit = true; targetHits += 1; totalScore += 220; sound("collect");
        if (targetHits === targets.length) nextPhase("obstacles");
      },
      update(dt) {
        if (phase === "targets") {
          targets.forEach(target => {
            if (target.hit) return;
            target.x += target.vx * dt; target.y += target.vy * dt;
            if (target.x < 100 || target.x > 1180) target.vx *= -1;
            if (target.y < 125 || target.y > 610) target.vy *= -1;
          });
          setHud(targetHits + "/" + targets.length, "Targets", "1 of 3", "Training", "Tap every moving power target");
        } else if (phase === "obstacles") {
          if (input.action && !jumpLatch && athlete.onGround) { athlete.velocity = -720; athlete.onGround = false; jumpLatch = true; sound("jump"); }
          if (!input.action) jumpLatch = false;
          athlete.velocity += 1700 * dt; athlete.y += athlete.velocity * dt;
          if (athlete.y >= 574) { athlete.y = 574; athlete.velocity = 0; athlete.onGround = true; }
          obstacleTimer -= dt;
          if (obstacleTimer <= 0 && obstaclesSpawned < 8) {
            obstacles.push({ x: 1330, used: false, counted: false }); obstaclesSpawned += 1; obstacleTimer = 1.05 + random() * .38;
          }
          obstacles.forEach(item => {
            item.x -= 385 * dt;
            if (!item.used && Math.abs(item.x - athlete.x) < 58 && athlete.y > 500) { item.used = true; obstacleHits += 1; sound("bump"); }
            if (!item.counted && item.x < athlete.x - 80) { item.counted = true; obstaclesPassed += 1; if (!item.used) totalScore += 180; }
          });
          obstacles = obstacles.filter(item => item.x > -100);
          setHud(obstaclesPassed + "/8", "Obstacles", "2 of 3", "Training", "JUMP over each training block");
          if (obstaclesPassed >= 8) nextPhase("flight");
        } else {
          const speed = input.action ? 390 : 285;
          flyer.x = clamp(flyer.x + (Number(input.right) - Number(input.left)) * speed * dt, 90, 620);
          flyer.y = clamp(flyer.y + (Number(input.down) - Number(input.up)) * speed * dt, 100, 620);
          ringTimer -= dt;
          if (ringTimer <= 0 && ringsPassed < 7) {
            rings.push({ x: 1370, y: 145 + random() * 430, counted: false, spin: random() * Math.PI }); ringTimer = 1.15 + random() * .35;
          }
          rings.forEach(ring => {
            ring.x -= (input.action ? 390 : 300) * dt;
            if (!ring.counted && ring.x < flyer.x + 15) {
              ring.counted = true; ringsPassed += 1;
              if (Math.abs(ring.y - flyer.y) < 90) { totalScore += 260; sound("collect"); }
              else { ringsMissed += 1; sound("wrong"); }
            }
          });
          rings = rings.filter(ring => ring.x > -120);
          setHud(ringsPassed + "/7", "Flying rings", "3 of 3", "Training", input.action ? "Super boost active!" : "Fly through the middle of every ring");
          if (ringsPassed >= 7) finishGame(totalScore >= 3000 ? 3 : totalScore >= 2100 ? 2 : 1, totalScore, "Academy complete! Three superhero challenges mastered.");
        }
      },
      draw() {
        if (phase === "targets") {
          drawBackdrop(0, 520);
          ctx.fillStyle = "#24305f55"; for (let x = 40; x < 1280; x += 140) { roundedRect(ctx, x, 95, 90, 510, 30); ctx.fill(); }
          targets.forEach((target, index) => {
            if (target.hit) return;
            const pulse = 1 + Math.sin(elapsed * 5 + index) * .12;
            ctx.strokeStyle = "#fff"; ctx.lineWidth = 8; ctx.fillStyle = ["#ff5f86", "#56d7ef", "#8f6ceb"][index % 3]; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 20;
            ctx.beginPath(); ctx.arc(target.x, target.y, target.radius * pulse, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
            ctx.font = target.radius + "px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(target.symbol, target.x, target.y);
          });
          drawCharacter(images[0], 105, 620, 135, { bob: Math.sin(elapsed * 4) * 5 });
        } else if (phase === "obstacles") {
          drawBackdrop(elapsed * 300, 500); ctx.fillStyle = "#e5c578"; ctx.fillRect(0, 620, 1280, 100);
          obstacles.forEach(item => { if (!item.used) { ctx.fillStyle = "#6e4bd3"; roundedRect(ctx, item.x - 38, 515, 76, 100, 18); ctx.fill(); ctx.fillStyle = "#fff"; ctx.font = "40px system-ui"; ctx.textAlign = "center"; ctx.fillText("⚡", item.x, 575); } });
          drawCharacter(images[0], athlete.x, athlete.y - 62, 130, { bob: athlete.onGround ? Math.sin(elapsed * 12) * 4 : 0 });
          drawCharacter(images[1], 1095, 180, 120, { ring: true, glow: "#fff6b5" });
        } else {
          drawBackdrop(elapsed * 160, 600);
          for (const ring of rings) {
            ctx.save(); ctx.translate(ring.x, ring.y); ctx.rotate(ring.spin + elapsed); ctx.strokeStyle = "#ffe34e"; ctx.lineWidth = 18; ctx.shadowColor = "#ffe34e"; ctx.shadowBlur = 25; ctx.beginPath(); ctx.ellipse(0, 0, 62, 90, 0, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
          }
          if (input.action) { ctx.strokeStyle = "#60e8ff99"; ctx.lineWidth = 11; for (let i = 0; i < 4; i += 1) { ctx.beginPath(); ctx.moveTo(flyer.x - 160 - i * 30, flyer.y - 35 + i * 24); ctx.lineTo(flyer.x - 50, flyer.y - 35 + i * 24); ctx.stroke(); } }
          drawCharacter(images[0], flyer.x, flyer.y, 135, { bob: Math.sin(elapsed * 7) * 4 });
        }
      }
    };
  }

  const FOOD = [
    { icon: "🍎", name: "apple" }, { icon: "🧁", name: "cupcake" }, { icon: "🥪", name: "sandwich" },
    { icon: "🥛", name: "milk" }, { icon: "🍓", name: "strawberry" }, { icon: "🍪", name: "biscuit" }
  ];

  function cafeGame() {
    const random = seededRandom(plan.seed);
    let served = 0;
    let order = [];
    let prepared = [];
    let happy = 0;
    let shake = 0;
    function makeOrder() {
      const length = served < 2 ? 2 : served < 4 ? 3 : 4;
      order = shuffle(random, FOOD).slice(0, length);
      prepared = [];
    }
    function renderControls() {
      controls.innerHTML = '<div class="food-controls" aria-label="Café ingredients">' + FOOD.map((food, index) => `<button class="food-button" type="button" data-food="${index}">${food.icon}<small>${food.name}</small></button>`).join("") + "</div>";
      controls.querySelectorAll("[data-food]").forEach(button => button.addEventListener("click", () => chooseFood(Number(button.dataset.food))));
    }
    function chooseFood(index) {
      if (!running || paused || completed) return;
      unlockAudio();
      const expected = order[prepared.length];
      if (!expected || FOOD[index].name !== expected.name) { shake = .35; sound("wrong"); toast("Check the order card and try again!"); return; }
      prepared.push(FOOD[index]); sound("collect");
      if (prepared.length === order.length) {
        served += 1; happy += order.length * 200; sound("correct"); toast("Order served! Happy customer " + served + " of 5");
        if (served >= 5) { setTimeout(() => finishGame(3, happy, "Café complete! Every customer loved their order."), 450); }
        else setTimeout(makeOrder, 500);
      }
    }
    makeOrder();
    return {
      start() { renderControls(); },
      update(dt) {
        shake = Math.max(0, shake - dt);
        setHud(served + "/5", "Happy customers", prepared.length + "/" + order.length, "Order ready", "Tap each item in the same order as the customer's card");
      },
      draw() {
        const palette = WORLD_PALETTES[plan.world] || WORLD_PALETTES["Rainbow City"];
        const gradient = ctx.createLinearGradient(0, 0, 0, 720); gradient.addColorStop(0, palette[0]); gradient.addColorStop(1, "#fff1d5"); ctx.fillStyle = gradient; ctx.fillRect(0, 0, 1280, 720);
        ctx.fillStyle = "#ffffffc9"; roundedRect(ctx, 60, 80, 1160, 540, 38); ctx.fill();
        ctx.fillStyle = "#db8a4a"; roundedRect(ctx, 0, 530, 1280, 190, 20); ctx.fill();
        ctx.fillStyle = "#9d542f"; ctx.fillRect(0, 620, 1280, 35);
        for (let x = 90; x < 1200; x += 175) { ctx.fillStyle = "#ffffff55"; roundedRect(ctx, x, 110, 120, 110, 22); ctx.fill(); ctx.font = "58px system-ui"; ctx.textAlign = "center"; ctx.fillText(FOOD[(x / 175) % FOOD.length | 0].icon, x + 60, 184); }
        const customerImage = served % 2 ? images[1] : images[0];
        drawCharacter(customerImage, 245, 420, 245, { bob: Math.sin(elapsed * 3) * 5 });
        ctx.save(); ctx.translate(shake ? Math.sin(elapsed * 45) * 16 : 0, 0);
        ctx.fillStyle = "#fff"; ctx.strokeStyle = "#6c4ad4"; ctx.lineWidth = 8; roundedRect(ctx, 505, 155, 630, 270, 35); ctx.fill(); ctx.stroke();
        ctx.fillStyle = "#4c38b2"; ctx.font = "1000 28px Trebuchet MS"; ctx.textAlign = "center"; ctx.fillText("TODAY'S ORDER", 820, 205);
        order.forEach((food, index) => {
          const x = 590 + index * 150;
          ctx.globalAlpha = index < prepared.length ? .32 : 1;
          ctx.font = "72px system-ui"; ctx.fillText(food.icon, x, 315);
          ctx.fillStyle = "#263b6b"; ctx.font = "900 18px Trebuchet MS"; ctx.fillText(food.name, x, 354);
          if (index < prepared.length) { ctx.globalAlpha = 1; ctx.fillStyle = "#32bd70"; ctx.font = "38px system-ui"; ctx.fillText("✓", x, 280); }
        });
        ctx.restore();
        ctx.fillStyle = "#fff0"; drawCharacter(images[1], 1090, 545, 125, { bob: Math.sin(elapsed * 4 + 2) * 4 });
      }
    };
  }

  function danceGame() {
    const random = seededRandom(plan.seed);
    const laneIcons = ["←", "↑", "↓", "→"];
    const laneColours = ["#ff5e84", "#56d9ef", "#ffd84d", "#8b68ed"];
    const notes = Array.from({ length: 28 }, (_, index) => ({ lane: Math.floor(random() * 4), time: 1.3 + index * .64 + random() * .12, judged: false, hit: false }));
    let songTime = 0;
    let score = 0;
    let combo = 0;
    let bestCombo = 0;
    let hits = 0;
    function pressLane(lane) {
      if (!running || paused || completed) return;
      unlockAudio();
      const candidates = notes.filter(note => !note.judged && note.lane === lane).sort((a, b) => Math.abs(a.time - songTime) - Math.abs(b.time - songTime));
      const note = candidates[0];
      if (!note || Math.abs(note.time - songTime) > .32) { combo = 0; sound("wrong"); return; }
      const accuracy = Math.abs(note.time - songTime);
      note.judged = true; note.hit = true; hits += 1; combo += 1; bestCombo = Math.max(bestCombo, combo); score += accuracy < .12 ? 300 : 180;
      tone(420 + lane * 115, .09, "triangle", .045, 90); toast(accuracy < .12 ? "Perfect! ×" + combo : "Great! ×" + combo);
    }
    function renderControls() {
      controls.innerHTML = '<div class="dance-controls" aria-label="Dance moves">' + laneIcons.map((icon, index) => `<button class="dance-button" type="button" data-lane="${index}" style="background:${laneColours[index]}55">${icon}<small>MOVE</small></button>`).join("") + "</div>";
      controls.querySelectorAll("[data-lane]").forEach(button => button.addEventListener("pointerdown", event => { event.preventDefault(); button.classList.add("active"); pressLane(Number(button.dataset.lane)); setTimeout(() => button.classList.remove("active"), 120); }));
    }
    return {
      start() { renderControls(); },
      pressLane,
      update(dt) {
        songTime += dt;
        for (const note of notes) {
          if (!note.judged && songTime - note.time > .36) { note.judged = true; combo = 0; }
        }
        if (Math.floor(songTime * 2) !== Math.floor((songTime - dt) * 2)) sound("beat");
        setHud(score, "Dance score", combo ? "×" + combo : "Ready", "Combo", "Tap a move when it reaches the glowing beat line");
        if (songTime > notes[notes.length - 1].time + 1) finishGame(hits >= 24 ? 3 : hits >= 17 ? 2 : 1, score + bestCombo * 50, "Dance complete! Best combo ×" + bestCombo + ".");
      },
      draw() {
        const gradient = ctx.createLinearGradient(0, 0, 0, 720); gradient.addColorStop(0, "#271858"); gradient.addColorStop(1, "#8634a5"); ctx.fillStyle = gradient; ctx.fillRect(0, 0, 1280, 720);
        for (let index = 0; index < 36; index += 1) { const x = (index * 173 + plan.seed) % 1280, y = (index * 97) % 620; ctx.fillStyle = laneColours[index % 4] + "66"; ctx.beginPath(); ctx.arc(x, y, 3 + index % 5, 0, Math.PI * 2); ctx.fill(); }
        ctx.fillStyle = "#ffffff12"; roundedRect(ctx, 315, 45, 650, 625, 34); ctx.fill();
        const laneWidth = 145, startX = 350;
        laneColours.forEach((colour, lane) => { ctx.fillStyle = colour + "22"; ctx.fillRect(startX + lane * laneWidth, 70, laneWidth - 8, 560); ctx.fillStyle = colour; ctx.globalAlpha = .85; ctx.font = "900 68px Trebuchet MS"; ctx.textAlign = "center"; ctx.fillText(laneIcons[lane], startX + lane * laneWidth + laneWidth / 2 - 4, 610); ctx.globalAlpha = 1; });
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 10; ctx.shadowColor = "#fff"; ctx.shadowBlur = 20; ctx.beginPath(); ctx.moveTo(345, 535); ctx.lineTo(925, 535); ctx.stroke(); ctx.shadowBlur = 0;
        for (const note of notes) {
          if (note.judged) continue;
          const y = 535 - (note.time - songTime) * 390;
          if (y < -80 || y > 610) continue;
          const x = startX + note.lane * laneWidth + laneWidth / 2 - 4;
          ctx.fillStyle = laneColours[note.lane]; ctx.strokeStyle = "#fff"; ctx.lineWidth = 5; ctx.shadowColor = laneColours[note.lane]; ctx.shadowBlur = 18; ctx.beginPath(); ctx.arc(x, y, 41, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
          ctx.fillStyle = "#fff"; ctx.font = "900 45px Trebuchet MS"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(laneIcons[note.lane], x, y);
        }
        drawCharacter(images[0], 165, 470, 225, { bob: Math.sin(elapsed * 8) * 18 });
        drawCharacter(images[1], 1110, 470, 225, { bob: Math.sin(elapsed * 8 + Math.PI) * 18, flip: true });
      }
    };
  }

  function hideGame() {
    const random = seededRandom(plan.seed);
    const worldWidth = 2600;
    let camera = 0;
    let found = 0;
    let hint = 0;
    let dragStart = null;
    let hintLatch = false;
    const symbols = shuffle(random, ["🧸", "🎈", "🦋", "⚽", "🎀", "🪁"]);
    const spots = shuffle(random, [220, 510, 790, 1080, 1380, 1680, 1980, 2310]);
    const items = spots.slice(0, 6).map((x, index) => ({ x, y: 185 + random() * 355, found: false, type: index < 2 ? "friend" : "symbol", symbol: symbols[index], image: images[index % 2], size: index < 2 ? 86 : 48 }));
    function tap(x, y) {
      const worldX = x + camera;
      const item = items.find(target => !target.found && Math.hypot(target.x - worldX, target.y - y) < target.size + 30);
      if (!item) { sound("wrong"); toast("Keep looking. Some hiding places are sneaky!"); return; }
      item.found = true; found += 1; hint = 0; sound("collect"); toast("Found " + found + " of " + items.length + "!");
      if (found === items.length) setTimeout(() => finishGame(3, 3000, "Everyone found! You searched the whole world."), 350);
    }
    return {
      start() { setControls("search"); },
      pointerDown(point) { dragStart = { x: point.x, camera }; },
      pointerMove(point) { if (dragStart) camera = clamp(dragStart.camera - (point.x - dragStart.x) * 1.6, 0, worldWidth - 1280); },
      pointerUp() { dragStart = null; },
      handleTap: tap,
      update(dt) {
        camera = clamp(camera + (Number(input.right) - Number(input.left)) * 420 * dt, 0, worldWidth - 1280);
        if (input.action && !hintLatch) {
          hintLatch = true; const target = items.find(item => !item.found); if (target) { hint = 3; camera = clamp(target.x - 640, 0, worldWidth - 1280); sound("correct"); toast("Hint: something is twinkling nearby!"); }
        }
        if (!input.action) hintLatch = false;
        hint = Math.max(0, hint - dt);
        setHud(found + "/" + items.length, "Friends found", Math.round(camera / (worldWidth - 1280) * 100) + "%", "World explored", "Drag to explore, then tap hidden friends and objects");
      },
      draw() {
        drawBackdrop(camera, 500);
        const base = -camera;
        for (let index = 0; index < 18; index += 1) {
          const x = base + 95 + index * 150;
          ctx.fillStyle = index % 3 ? "#237d53" : "#7350a6"; ctx.fillRect(x - 12, 325 + index % 2 * 80, 24, 220);
          ctx.fillStyle = index % 3 ? "#32a96c" : "#986cd3"; ctx.beginPath(); ctx.arc(x, 310 + index % 2 * 80, 75, 0, Math.PI * 2); ctx.fill();
          if (index % 4 === 0) { ctx.fillStyle = "#f4c866"; roundedRect(ctx, x + 38, 480, 105, 85, 14); ctx.fill(); }
        }
        ctx.fillStyle = "#e7c77e"; ctx.fillRect(0, 620, 1280, 100);
        items.forEach((item, index) => {
          if (item.found) return;
          const x = item.x - camera;
          if (x < -130 || x > 1410) return;
          const twinkle = hint > 0 && item === items.find(target => !target.found);
          if (twinkle) { ctx.strokeStyle = "#ffe33d"; ctx.lineWidth = 8; ctx.shadowColor = "#ffe33d"; ctx.shadowBlur = 25; ctx.beginPath(); ctx.arc(x, item.y, item.size + 27 + Math.sin(elapsed * 7) * 8, 0, Math.PI * 2); ctx.stroke(); ctx.shadowBlur = 0; }
          if (item.type === "friend") drawCharacter(item.image, x, item.y, item.size * 2, { alpha: .78, bob: Math.sin(elapsed * 3 + index) * 3 });
          else { ctx.font = item.size * 1.8 + "px system-ui"; ctx.textAlign = "center"; ctx.globalAlpha = .82; ctx.fillText(item.symbol, x, item.y + item.size * .5); ctx.globalAlpha = 1; }
        });
        ctx.fillStyle = "#102750d5"; roundedRect(ctx, 465, 655, 350, 36, 18); ctx.fill();
        ctx.fillStyle = "#58d7ee"; roundedRect(ctx, 470, 660, 340 * camera / (worldWidth - 1280), 26, 13); ctx.fill();
      }
    };
  }

  const GAME_BUILDERS = { rescue: rescueGame, kart: kartGame, runner: runnerGame, academy: academyGame, cafe: cafeGame, dance: danceGame, hide: hideGame };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
  }

  function teamMarkup() {
    return plan.characters.map((character, index) => `<div class="team-character"><img src="${escapeHtml(ProfileShell.url(character.image))}" alt="${escapeHtml(character.theme_label)} character"><span>${escapeHtml(character.theme_label)}</span></div>${index === 0 ? '<strong aria-hidden="true">+</strong>' : ""}`).join("");
  }

  function showIntro() {
    byId("teamTitle").textContent = plan.theme_labels.join(" + ") + " in " + plan.world;
    overlayCard.innerHTML = `<span class="overlay-eyebrow">${escapeHtml(config.eyebrow)} • Mission ${plan.mission_number}</span>
      <h2>${escapeHtml(config.short)}</h2>
      <div class="team-preview">${teamMarkup()}</div>
      <p><strong>${escapeHtml(plan.world)}</strong></p><p>${escapeHtml(config.instruction)}</p>
      <div class="overlay-actions"><button class="primary-game-button" id="startGame" type="button">Start mission</button><a class="secondary-game-button" href="../" style="display:inline-grid;place-items:center;text-decoration:none">Choose another game</a></div>`;
    overlay.hidden = false;
    byId("startGame").onclick = startGame;
  }

  function startGame() {
    unlockAudio();
    clearInput();
    completed = false; paused = false; elapsed = 0;
    game = GAME_BUILDERS[gameKey]();
    setControls(config.controls);
    game.start?.();
    overlay.hidden = true;
    running = true;
    lastFrame = performance.now();
  }

  async function finishGame(stars, score, message) {
    if (completed) return;
    completed = true; running = false; clearInput(); sound("win"); confetti();
    const safeStars = clamp(Math.round(stars), 1, 3);
    overlayCard.innerHTML = `<span class="overlay-eyebrow">Mission complete</span><h2>${escapeHtml(message)}</h2>
      <div class="result-stars" aria-label="${safeStars} out of 3 stars">${"★".repeat(safeStars)}${"☆".repeat(3 - safeStars)}</div>
      <p><strong>${Math.max(0, Math.round(score)).toLocaleString("en-GB")} points</strong></p><p id="savingReward">Saving your result and preparing your sticker…</p>`;
    overlay.hidden = false;
    let result;
    try {
      result = await api("/api/progress/complete", { method: "POST", body: JSON.stringify({ activity: config.activity, item: "mission", attempt }) });
      byId("savingReward").textContent = result.parent_preview ? "Parent preview complete. Play another mission whenever you like." : "Your mission is saved. Choose your sticker, then start a brand-new adventure.";
      overlayCard.insertAdjacentHTML("beforeend", `<div class="overlay-actions"><button class="primary-game-button" id="newMission" type="button">New random mission</button><a class="secondary-game-button" href="../" style="display:inline-grid;place-items:center;text-decoration:none">All games</a></div>`);
      byId("newMission").onclick = () => loadRound(true);
      if (result.reward_token) ProfileShell.claimReward(result.reward_token).catch(() => {});
    } catch (error) {
      byId("savingReward").innerHTML = `<span class="game-error">${escapeHtml(error.message)}</span>`;
      overlayCard.insertAdjacentHTML("beforeend", '<div class="overlay-actions"><button class="primary-game-button" id="retrySave" type="button">Try saving again</button><a class="secondary-game-button" href="../" style="display:inline-grid;place-items:center;text-decoration:none">All games</a></div>');
      byId("retrySave").onclick = () => { completed = false; finishGame(stars, score, message); };
    }
  }

  async function loadRound(newRound = false) {
    running = false; completed = false; paused = false; clearInput();
    byId("hud").hidden = true; byId("objectiveBar").hidden = true; controls.innerHTML = "";
    overlayCard.innerHTML = '<div class="loading-spinner"></div><h2>Building your adventure…</h2><p>Choosing two surprise characters and a brand-new world.</p>';
    overlay.hidden = false;
    try {
      if (newRound && ProfileShell.profile === ProfileShell.parentProfile) await api("/api/progress/reset", { method: "POST", body: JSON.stringify({ activities: [config.activity] }) });
      const variant = await api("/api/activity/variant?activity=" + encodeURIComponent(config.activity));
      attempt = variant.attempt; plan = variant.plan;
      const loaded = await Promise.all(plan.characters.map(character => imagePromise(character.image)));
      images.splice(0, images.length, ...loaded);
      showIntro();
    } catch (error) {
      overlayCard.innerHTML = `<div class="overlay-eyebrow">Could not load</div><h2>Game paused</h2><p class="game-error">${escapeHtml(error.message)}</p><div class="overlay-actions"><button class="primary-game-button" id="tryLoad" type="button">Try again</button><a class="secondary-game-button" href="../" style="display:inline-grid;place-items:center;text-decoration:none">All games</a></div>`;
      byId("tryLoad").onclick = () => loadRound(newRound);
    }
  }

  function showPause() {
    if (!running || completed) return;
    paused = true; clearInput();
    overlayCard.innerHTML = `<div class="overlay-eyebrow">Game paused</div><h2>Take a breather</h2><p>Your mission is waiting exactly where you left it.</p><div class="overlay-actions"><button class="primary-game-button" id="resumeGame" type="button">Keep playing</button><button class="secondary-game-button" id="restartGame" type="button">Restart mission</button><a class="secondary-game-button" href="../" style="display:inline-grid;place-items:center;text-decoration:none">All games</a></div>`;
    overlay.hidden = false;
    byId("resumeGame").onclick = () => { paused = false; overlay.hidden = true; lastFrame = performance.now(); };
    byId("restartGame").onclick = startGame;
  }

  function animate(time) {
    const dt = Math.min(.034, Math.max(0, (time - lastFrame) / 1000));
    lastFrame = time;
    if (running && !paused && game) { elapsed += dt; game.update(dt); }
    if (game) game.draw();
    requestAnimationFrame(animate);
  }

  const keyMap = { ArrowLeft: "left", a: "left", A: "left", ArrowRight: "right", d: "right", D: "right", ArrowUp: "up", w: "up", W: "up", ArrowDown: "down", s: "down", S: "down", " ": "action", Enter: "action", Shift: "alt" };
  addEventListener("keydown", event => {
    if (gameKey === "dance" && running && !paused) {
      const lanes = { ArrowLeft: 0, ArrowUp: 1, ArrowDown: 2, ArrowRight: 3 };
      if (event.key in lanes) { game?.pressLane?.(lanes[event.key]); event.preventDefault(); return; }
    }
    const key = keyMap[event.key]; if (!key) return; input[key] = true; event.preventDefault();
  });
  addEventListener("keyup", event => { const key = keyMap[event.key]; if (key) { input[key] = false; event.preventDefault(); } });
  addEventListener("blur", clearInput);

  canvas.addEventListener("pointerdown", event => {
    if (!running || paused || completed) return;
    unlockAudio(); const point = canvasPoint(event); pointerStart = point; pointerMoved = false; game?.pointerDown?.(point); canvas.setPointerCapture?.(event.pointerId); event.preventDefault();
  });
  canvas.addEventListener("pointermove", event => {
    if (!pointerStart || !running || paused) return;
    const point = canvasPoint(event); if (Math.hypot(point.x - pointerStart.x, point.y - pointerStart.y) > 14) pointerMoved = true; game?.pointerMove?.(point); event.preventDefault();
  });
  function endPointer(event) {
    if (!pointerStart) return;
    const point = canvasPoint(event); game?.pointerUp?.(point); if (!pointerMoved) game?.handleTap?.(point.x, point.y); pointerStart = null; pointerMoved = false; event.preventDefault();
  }
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", () => { pointerStart = null; pointerMoved = false; game?.pointerUp?.(); });

  byId("pauseButton").onclick = showPause;
  byId("soundButton").onclick = () => {
    audioEnabled = !audioEnabled; localStorage.setItem("littleLearnersGameSound", audioEnabled ? "on" : "off"); byId("soundButton").textContent = audioEnabled ? "🔊" : "🔇"; if (audioEnabled) { unlockAudio(); sound("correct"); }
  };

  ProfileShell.ready.then(() => loadRound());
  requestAnimationFrame(animate);
})();
