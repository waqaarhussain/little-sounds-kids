(function () {
  "use strict";

  let profile = null;
  let selectedProfile = null;
  let profiles = ["Parent", "Child 1", "Child 2"];
  let parentProfile = "Parent";
  let childProfiles = ["Child 1", "Child 2"];
  let resolveReady;
  const ready = new Promise(resolve => { resolveReady = resolve; });
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
  const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  const basePath = location.pathname === "/test" || location.pathname.startsWith("/test/") ? "/test" : "";
  const pagePath = basePath ? location.pathname.slice(basePath.length) || "/" : location.pathname;
  const sitePath = path => {
    if (!String(path).startsWith("/") || !basePath || String(path).startsWith(basePath + "/")) return path;
    return basePath + path;
  };

  async function api(path, options = {}) {
    const response = await fetch(sitePath(path), {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || "Something went wrong.");
    return result;
  }

  function initials(name) {
    const words = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return "??";
    if (words.length > 1) return (words[0][0] + words[words.length - 1][0]).toUpperCase();
    return (words[0][0] + "H").toUpperCase();
  }

  function createInterface() {
    const phonicsTools = pagePath.startsWith("/phonicsbook")
      ? '<button class="site-tool-button site-tool-icon" id="siteAlphabetButton" type="button" aria-label="Choose a letter">🔤</button>'
      : "";
    document.body.insertAdjacentHTML("beforeend", `
      <a class="site-brand" href="${sitePath("/")}" aria-label="Little Learners home"><span class="site-brand-mark">📚</span><span>Little Learners</span></a>
      <nav class="site-tools" aria-label="Site controls">
        <a class="site-tool-button site-tool-icon" href="${sitePath("/")}" aria-label="Little Learners home">🏠</a>
        ${phonicsTools}
        <button class="site-tool-button site-tool-icon" id="siteGiveSticker" type="button" aria-label="Give a good behaviour sticker">🎁</button>
        <a class="site-tool-button site-tool-icon" href="${sitePath("/stickers/")}" aria-label="Open earned sticker album">🌟</a>
        <button class="site-tool-button site-profile-initials" id="siteProfileButton" type="button" aria-label="Switch profile"><span id="siteProfileName">?</span></button>
      </nav>
      <a class="site-books-link" href="${sitePath("/books/")}" aria-label="Open the Little Learners book shelf">📖</a>
      <div class="site-modal" id="profileModal" hidden>
        <section class="site-modal-card" role="dialog" aria-modal="true" aria-labelledby="profileTitle">
          <h2 id="profileTitle">Choose Profile</h2>
          <p id="profileHelp" hidden></p>
          <div class="profile-grid" id="profileGrid"></div>
          <div class="profile-pin" id="profilePin" hidden>
            <label for="profilePinInput"><strong>Parent PIN</strong></label>
            <input id="profilePinInput" type="password" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="••••">
          </div>
          <p class="profile-error" id="profileError" role="alert"></p>
          <div class="site-actions" id="profileActions" hidden>
            <button class="site-primary" id="profileConfirm" type="button">Switch profile</button>
            <button class="site-secondary" id="profileCancel" type="button">Cancel</button>
          </div>
        </section>
      </div>
      <div class="site-modal" id="rewardModal" hidden>
        <section class="site-modal-card reward-modal-card" id="rewardCard" role="dialog" aria-modal="true"></section>
      </div>`);
  }

  function profileButtons(choices = profiles) {
    const icons = ["🧑", "🌈", "⭐"];
    return choices.map((name, index) => `
      <button class="profile-choice" type="button" data-profile="${escapeHtml(name)}">
        <span>${icons[index] || "👤"}</span>${escapeHtml(name)}
      </button>`).join("");
  }

  function setProfile(name) {
    profile = name;
    document.getElementById("siteProfileName").textContent = initials(name);
    document.getElementById("siteProfileButton").setAttribute("aria-label", "Switch profile. Current profile " + name);
    document.documentElement.dataset.profile = name.toLowerCase();
    window.dispatchEvent(new CustomEvent("profilechange", { detail: { profile: name } }));
  }

  function openProfileModal(firstLaunch) {
    const modal = document.getElementById("profileModal");
    const grid = document.getElementById("profileGrid");
    const pin = document.getElementById("profilePin");
    const actions = document.getElementById("profileActions");
    const cancel = document.getElementById("profileCancel");
    const help = document.getElementById("profileHelp");
    document.getElementById("profileTitle").textContent = firstLaunch ? "Choose Profile" : "Switch Profile";
    help.textContent = firstLaunch ? "" : "Choose a profile and enter the parent PIN.";
    help.hidden = firstLaunch;
    document.getElementById("profileError").textContent = "";
    document.getElementById("profilePinInput").value = "";
    selectedProfile = null;
    grid.innerHTML = profileButtons();
    pin.hidden = firstLaunch;
    actions.hidden = firstLaunch;
    cancel.hidden = firstLaunch;
    modal.hidden = false;
    grid.querySelectorAll("button").forEach(button => button.addEventListener("click", async () => {
      selectedProfile = button.dataset.profile;
      grid.querySelectorAll("button").forEach(other => other.classList.toggle("selected", other === button));
      if (firstLaunch) {
        try {
          const result = await api("/api/profile/select", { method: "POST", body: JSON.stringify({ profile: selectedProfile }) });
          setProfile(result.profile);
          modal.hidden = true;
          resolveReady(result.profile);
        } catch (error) {
          document.getElementById("profileError").textContent = error.message;
        }
      } else document.getElementById("profilePinInput").focus();
    }));
  }

  async function confirmSwitch() {
    const errorBox = document.getElementById("profileError");
    if (!selectedProfile) {
      errorBox.textContent = "Choose a profile first.";
      return;
    }
    try {
      const result = await api("/api/profile/switch", {
        method: "POST",
        body: JSON.stringify({ profile: selectedProfile, pin: document.getElementById("profilePinInput").value })
      });
      setProfile(result.profile);
      document.getElementById("profileModal").hidden = true;
      location.reload();
    } catch (error) {
      errorBox.textContent = error.message;
      document.getElementById("profilePinInput").select();
    }
  }

  function showRewardError(error, retry = null) {
    const modal = document.getElementById("rewardModal");
    const card = document.getElementById("rewardCard");
    card.innerHTML = `
      <div class="reward-symbol">💭</div><h2>Oops!</h2><p>${escapeHtml(error.message || error)}</p>
      <div class="site-actions">
        ${retry ? '<button class="site-primary" type="button" id="rewardRetry">Try again</button>' : ""}
        <button class="site-secondary" type="button" id="rewardClose">Close</button>
      </div>`;
    modal.hidden = false;
    document.getElementById("rewardClose").onclick = () => { modal.hidden = true; };
    if (retry) document.getElementById("rewardRetry").onclick = retry;
  }

  function openBonusReward() {
    const modal = document.getElementById("rewardModal");
    const card = document.getElementById("rewardCard");
    const defaultChild = childProfiles.includes(profile) ? profile : childProfiles[0];
    card.innerHTML = `
      <div class="reward-symbol">🎁</div><h2>Give a sticker</h2><p>A special sticker for being brilliant!</p>
      <div class="bonus-profile-grid">
        ${childProfiles.map((name, index) => `
          <button class="profile-choice ${name === defaultChild ? "selected" : ""}" type="button" data-profile="${escapeHtml(name)}">
            <span>${index ? "⭐" : "🌈"}</span>${escapeHtml(name)}
          </button>`).join("")}
      </div>
      <div class="profile-pin bonus-pin"><label for="bonusPin"><strong>Parent PIN</strong></label>
        <input id="bonusPin" type="password" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="••••"></div>
      <p class="profile-error" id="bonusError" role="alert"></p>
      <div class="site-actions"><button class="site-primary" id="bonusContinue" type="button">Choose a sticker</button>
        <button class="site-secondary" id="bonusCancel" type="button">Cancel</button></div>`;
    modal.hidden = false;
    let targetProfile = defaultChild;
    card.querySelectorAll(".bonus-profile-grid button").forEach(button => button.addEventListener("click", () => {
      targetProfile = button.dataset.profile;
      card.querySelectorAll(".bonus-profile-grid button").forEach(other => other.classList.toggle("selected", other === button));
    }));
    document.getElementById("bonusCancel").onclick = () => { modal.hidden = true; };
    document.getElementById("bonusContinue").onclick = async () => {
      const button = document.getElementById("bonusContinue");
      const errorBox = document.getElementById("bonusError");
      button.disabled = true;
      errorBox.textContent = "";
      try {
        const result = await api("/api/rewards/bonus", {
          method: "POST",
          body: JSON.stringify({ profile: targetProfile, pin: document.getElementById("bonusPin").value })
        });
        await claimReward(result.reward_token);
      } catch (error) {
        errorBox.textContent = error.message;
        button.disabled = false;
        document.getElementById("bonusPin")?.select();
      }
    };
    document.getElementById("bonusPin").addEventListener("keydown", event => {
      if (event.key === "Enter") document.getElementById("bonusContinue").click();
    });
    setTimeout(() => document.getElementById("bonusPin")?.focus(), 80);
  }

  async function chooseStickerTheme(categories, rewardToken, rewardProfile) {
    const modal = document.getElementById("rewardModal");
    const card = document.getElementById("rewardCard");
    card.innerHTML = `
      <div class="reward-symbol">✨</div><h2>${escapeHtml(rewardProfile)}, choose a theme!</h2>
      <p>Which sticker sheet would you like?</p>
      <div class="sticker-choice-grid">
        ${categories.map(category => `
          <button class="sticker-choice" type="button" data-category="${escapeHtml(category.id)}">
            <img src="${escapeHtml(category.image)}" alt=""><span>${escapeHtml(category.label)}</span>
            <small>${category.available} ready</small>
          </button>`).join("")}
      </div>
      <div class="site-actions"><button class="site-secondary" type="button" id="rewardClose">Not now</button></div>`;
    modal.hidden = false;
    document.getElementById("rewardClose").onclick = () => { modal.hidden = true; };
    card.querySelectorAll(".sticker-choice").forEach(button => button.addEventListener("click", () => {
      openStickerSheet(button.dataset.category, rewardToken);
    }));
  }

  async function openStickerSheet(category, rewardToken) {
    const modal = document.getElementById("rewardModal");
    const card = document.getElementById("rewardCard");
    card.innerHTML = '<div class="sticker-sheet-loading">Opening your sticker sheet… ✨</div>';
    try {
      const book = await api("/api/sticker-book?category=" + encodeURIComponent(category) + "&reward_token=" + encodeURIComponent(rewardToken));
      card.innerHTML = `
        <div class="sticker-sheet-header">
          <div><span class="sheet-kicker">${escapeHtml(book.profile)}'s sticker sheet</span><h2>${escapeHtml(book.category_label)}</h2></div>
          <button class="sheet-close" type="button" id="rewardClose" aria-label="Close">×</button>
        </div>
        <p>Tap one sticker and watch the magic!</p>
        <div class="sticker-sheet ${book.category === "alphablocks" ? "alphabet-sheet" : ""}" aria-label="${escapeHtml(book.category_label)} sticker sheet">
          ${book.slots.map(sticker => `
            <button class="sticker-slot available" type="button" data-sticker-id="${sticker.id}"
                    aria-label="${sticker.letter ? "Letter " + sticker.letter + ", " : ""}sticker ${sticker.serial}">
              <span class="peel-mark"><strong>${sticker.letter ? sticker.letter : "#" + sticker.serial}</strong></span>
              <img src="${escapeHtml(sticker.image)}" alt="${escapeHtml(book.category_label)} sticker ${sticker.serial}" loading="lazy">
              <span class="magic-sparkles" aria-hidden="true">✦ ✨ ★ ✦</span>
            </button>`).join("")}
        </div><p class="sheet-count">Showing ${book.shown} unused sticker${book.shown === 1 ? "" : "s"}</p>`;
      document.getElementById("rewardClose").onclick = () => { modal.hidden = true; };
      card.querySelectorAll(".sticker-slot.available").forEach(button => button.addEventListener("click", async () => {
        if (card.classList.contains("claiming")) return;
        card.classList.add("claiming");
        button.classList.add("peel-ready");
        card.querySelectorAll(".sticker-slot.available").forEach(item => { if (item !== button) item.classList.add("fade-away"); });
        try {
          const reward = await api("/api/rewards/claim", {
            method: "POST", body: JSON.stringify({ reward_token: rewardToken, sticker_id: Number(button.dataset.stickerId) })
          });
          await animateStickerPeel(button);
          showClaimedSticker(reward);
        } catch (error) {
          card.classList.remove("claiming");
          showRewardError(error, () => openStickerSheet(category, rewardToken));
        }
      }));
    } catch (error) { showRewardError(error); }
  }

  async function animateStickerPeel(button) {
    const image = button.querySelector("img");
    if (!image) { await wait(700); return; }
    const rect = image.getBoundingClientRect();
    const ghost = document.createElement("div");
    ghost.className = "peel-ghost";
    ghost.style.left = rect.left + "px";
    ghost.style.top = rect.top + "px";
    ghost.style.width = rect.width + "px";
    ghost.style.height = rect.height + "px";
    ghost.appendChild(image.cloneNode(true));
    document.body.appendChild(ghost);
    button.classList.remove("peel-ready");
    button.classList.add("peeled-hole");
    const centreX = innerWidth / 2 - (rect.left + rect.width / 2);
    const centreY = innerHeight / 2 - (rect.top + rect.height / 2);
    const scale = Math.min(3.2, Math.max(1.7, 330 / Math.max(rect.width, 1)));
    for (let index = 0; index < 22; index += 1) {
      const sparkle = document.createElement("i");
      sparkle.className = "screen-sparkle";
      sparkle.textContent = ["✦", "★", "✨", "●"][index % 4];
      const angle = index * Math.PI * 2 / 22;
      const distance = 90 + Math.random() * 150;
      sparkle.style.setProperty("--x", (Math.cos(angle) * distance) + "px");
      sparkle.style.setProperty("--y", (Math.sin(angle) * distance) + "px");
      sparkle.style.setProperty("--delay", (Math.random() * 220) + "ms");
      document.body.appendChild(sparkle);
      setTimeout(() => sparkle.remove(), 1800);
    }
    if (ghost.animate) {
      const animation = ghost.animate([
        { transform: "translate(0,0) perspective(700px) rotateY(0deg) rotateZ(0deg) scale(1)", offset: 0 },
        { transform: "translate(12px,-14px) perspective(700px) rotateY(-48deg) rotateZ(7deg) scale(1.08)", offset: .28 },
        { transform: "translate(" + (centreX * .58) + "px," + (centreY * .58 - 45) + "px) perspective(700px) rotateY(22deg) rotateZ(-8deg) scale(" + (scale * .78) + ")", offset: .68 },
        { transform: "translate(" + centreX + "px," + centreY + "px) perspective(700px) rotateY(0deg) rotateZ(0deg) scale(" + scale + ")", offset: 1 }
      ], { duration: 1450, easing: "cubic-bezier(.2,.8,.18,1)", fill: "forwards" });
      try { await animation.finished; } catch (_) {}
    } else await wait(1450);
    ghost.classList.add("peel-finish");
    await wait(350);
    ghost.remove();
  }

  function showClaimedSticker(reward) {
    const modal = document.getElementById("rewardModal");
    const card = document.getElementById("rewardCard");
    card.classList.remove("claiming");
    card.innerHTML = `
      <div class="reward-confetti" aria-hidden="true">✨ ⭐ 🎉 ⭐ ✨</div>
      <h2>Well done! Here is your sticker</h2>
      <p class="reward-number">Sticker ${reward.position} for ${escapeHtml(reward.profile)}</p>
      <img class="reward-image" src="${escapeHtml(reward.image)}" alt="${escapeHtml(reward.category_label)} reward sticker">
      <p>Your new ${escapeHtml(reward.category_label)} sticker is safely saved.</p>
      <div class="site-actions"><button class="site-primary" id="rewardContinue" type="button">Continue activity</button></div>`;
    modal.hidden = false;
    document.getElementById("rewardContinue").onclick = () => {
      modal.hidden = true;
      document.getElementById("gameButton")?.focus();
    };
  }

  async function claimReward(rewardToken) {
    await ready;
    try {
      const result = await api("/api/rewards/claim", { method: "POST", body: JSON.stringify({ reward_token: rewardToken }) });
      if (result.parent_preview) return result;
      if (result.needs_choice) await chooseStickerTheme(result.categories, rewardToken, result.profile);
      return result;
    } catch (error) {
      showRewardError(error);
      throw error;
    }
  }

  const inactivityLimit = 10 * 60 * 1000;
  let lastInteraction = Date.now();
  let lastSessionTouch = 0;
  let touchingSession = false;

  function currentActivity() {
    if (pagePath.startsWith("/handwriting")) return document.body.dataset.progressActivity || "letters";
    if (pagePath.startsWith("/phonicsbook")) return "phonics";
    if (pagePath.startsWith("/counting")) return "count-and-choose";
    if (pagePath.startsWith("/matching")) return "match-the-pairs";
    if (pagePath.startsWith("/sorting")) return "sort-colours-shapes";
    if (pagePath.startsWith("/patterns")) return "finish-the-pattern";
    if (pagePath.startsWith("/odd-one-out")) return "odd-one-out";
    if (pagePath.startsWith("/more-or-less")) return "more-or-less";
    return "";
  }

  async function touchActivitySession(force = false) {
    const activity = currentActivity();
    if (!activity || touchingSession || (!force && Date.now() - lastSessionTouch < 45000)) return;
    touchingSession = true;
    try {
      await ready;
      const result = await api("/api/progress/touch", {
        method: "POST",
        body: JSON.stringify({ activity })
      });
      lastSessionTouch = Date.now();
      if (result.expired) location.reload();
    } catch (_) {
      // Normal page requests will display service errors if the server is unavailable.
    } finally {
      touchingSession = false;
    }
  }

  function recordInteraction(event) {
    const idleFor = Date.now() - lastInteraction;
    lastInteraction = Date.now();
    if (idleFor >= inactivityLimit && currentActivity()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      location.reload();
      return;
    }
    touchActivitySession();
  }

  function startActivityTracking() {
    if (!currentActivity()) return;
    document.addEventListener("pointerdown", recordInteraction, true);
    document.addEventListener("keydown", recordInteraction, true);
    document.addEventListener("pointermove", () => { lastInteraction = Date.now(); }, { passive: true });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() - lastInteraction >= inactivityLimit) location.reload();
    });
    ready.then(() => touchActivitySession(true));
    setInterval(() => {
      if (!document.hidden && Date.now() - lastInteraction < 60000) touchActivitySession();
    }, 60000);
  }

  async function boot() {
    document.getElementById("siteProfileButton").addEventListener("click", () => openProfileModal(false));
    document.getElementById("siteGiveSticker").addEventListener("click", openBonusReward);
    document.getElementById("profileConfirm").addEventListener("click", confirmSwitch);
    document.getElementById("profilePinInput").addEventListener("keydown", event => { if (event.key === "Enter") confirmSwitch(); });
    document.getElementById("profileCancel").addEventListener("click", () => { document.getElementById("profileModal").hidden = true; });
    try {
      const status = await api("/api/profile");
      profiles = status.profiles || profiles;
      parentProfile = status.parent_profile || profiles[0];
      childProfiles = status.child_profiles || profiles.slice(1);
      if (status.profile) { setProfile(status.profile); resolveReady(status.profile); }
      else openProfileModal(true);
    } catch (error) {
      document.getElementById("profileError").textContent = "The profile service is not ready. Refresh the page in a moment.";
      openProfileModal(true);
    }
  }

  window.ProfileShell = Object.freeze({
    ready, claimReward, giveSticker: openBonusReward, url: sitePath,
    get parentProfile() { return parentProfile; },
    get childProfiles() { return [...childProfiles]; },
    get profile() { return profile; }
  });

  createInterface();
  startActivityTracking();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();