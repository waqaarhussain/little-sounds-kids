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

  async function api(path, options = {}) {
    const response = await fetch(path, {
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
    const phonicsTools = location.pathname.startsWith("/phonicsbook")
      ? '<button class="site-tool-button site-tool-icon" id="siteAlphabetButton" type="button" aria-label="Choose a letter">🔤</button>'
      : "";
    document.body.insertAdjacentHTML("beforeend", `
      <a class="site-brand" href="/" aria-label="Little Learners home"><span class="site-brand-mark">📚</span><span>Little Learners</span></a>
      <nav class="site-tools" aria-label="Site controls">
        <a class="site-tool-button site-tool-icon" href="/" aria-label="Little Learners home">🏠</a>
        ${phonicsTools}
        <button class="site-tool-button site-tool-icon" id="siteGiveSticker" type="button" aria-label="Give a good behaviour sticker">🎁</button>
        <a class="site-tool-button site-tool-icon" href="/stickers/" aria-label="Open earned sticker album">🌟</a>
        <button class="site-tool-button site-profile-initials" id="siteProfileButton" type="button" aria-label="Switch profile"><span id="siteProfileName">?</span></button>
      </nav>
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
        button.classList.add("magic-peel");
        card.querySelectorAll(".sticker-slot.available").forEach(item => { if (item !== button) item.classList.add("fade-away"); });
        try {
          const reward = await api("/api/rewards/claim", {
            method: "POST", body: JSON.stringify({ reward_token: rewardToken, sticker_id: Number(button.dataset.stickerId) })
          });
          await wait(1500);
          location.assign("/stickers/?profile=" + encodeURIComponent(reward.profile) + "&new=" + encodeURIComponent(reward.position));
        } catch (error) {
          card.classList.remove("claiming");
          showRewardError(error, () => openStickerSheet(category, rewardToken));
        }
      }));
    } catch (error) { showRewardError(error); }
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
    ready, claimReward, giveSticker: openBonusReward,
    get parentProfile() { return parentProfile; },
    get childProfiles() { return [...childProfiles]; },
    get profile() { return profile; }
  });

  createInterface();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();