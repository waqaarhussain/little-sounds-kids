(function () {
  "use strict";

  let profile = null;
  let selectedProfile = null;
  let profiles = ["Parent", "Child 1", "Child 2"];
  let parentProfile = "Parent";
  let childProfiles = ["Child 1", "Child 2"];
  let resolveReady;
  const ready = new Promise(resolve => { resolveReady = resolve; });

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

  function createInterface() {
    document.body.insertAdjacentHTML("beforeend", `
      <nav class="site-tools" aria-label="Profile and rewards">
        <a class="site-tool-button site-tool-sticker" href="/stickers/" aria-label="Open sticker book">🌟</a>
        <button class="site-tool-button" id="siteProfileButton" type="button" aria-label="Switch profile">👤 <span id="siteProfileName">Profile</span></button>
      </nav>
      <div class="site-modal" id="profileModal" hidden>
        <section class="site-modal-card" role="dialog" aria-modal="true" aria-labelledby="profileTitle">
          <h2 id="profileTitle">Who is playing?</h2>
          <p id="profileHelp">Pick your profile. This device will remember you.</p>
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
        <section class="site-modal-card" id="rewardCard" role="dialog" aria-modal="true"></section>
      </div>
    `);
  }

  function profileButtons() {
    const icons = ["🧑", "🌈", "⭐"];
    return profiles.map((name, index) => `
      <button class="profile-choice" type="button" data-profile="${name}">
        <span>${icons[index] || "👤"}</span>${name}
      </button>
    `).join("");
  }

  function setProfile(name) {
    profile = name;
    document.getElementById("siteProfileName").textContent = name;
    document.documentElement.dataset.profile = name.toLowerCase();
    window.dispatchEvent(new CustomEvent("profilechange", { detail: { profile: name } }));
  }

  function openProfileModal(firstLaunch) {
    const modal = document.getElementById("profileModal");
    const grid = document.getElementById("profileGrid");
    const pin = document.getElementById("profilePin");
    const actions = document.getElementById("profileActions");
    const cancel = document.getElementById("profileCancel");
    document.getElementById("profileTitle").textContent = firstLaunch ? "Who is playing?" : "Switch profile";
    document.getElementById("profileHelp").textContent = firstLaunch
      ? "Pick your profile. This device will remember you."
      : "Choose a profile and enter the parent PIN.";
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
      } else {
        document.getElementById("profilePinInput").focus();
      }
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

  async function chooseSticker(position, rewardToken) {
    const result = await api("/api/sticker-categories");
    const modal = document.getElementById("rewardModal");
    const card = document.getElementById("rewardCard");
    card.innerHTML = `
      <h2>Choose sticker ${position}!</h2>
      <p>The first child here chooses this sticker for both sticker books.</p>
      <div class="sticker-choice-grid">
        ${result.categories.map(category => `
          <button class="sticker-choice" type="button" data-category="${category.id}">
            <img src="${category.image}" alt=""><span>${category.label}</span>
          </button>
        `).join("")}
      </div>
    `;
    modal.hidden = false;
    return new Promise(resolve => {
      card.querySelectorAll("button").forEach(button => button.addEventListener("click", async () => {
        card.querySelectorAll("button").forEach(item => { item.disabled = true; });
        try {
          resolve(await api("/api/rewards/claim", {
            method: "POST",
            body: JSON.stringify({ category: button.dataset.category, reward_token: rewardToken })
          }));
        } catch (error) {
          card.innerHTML = `<h2>Oops</h2><p>${error.message}</p><div class="site-actions"><button class="site-secondary" type="button" id="rewardClose">Close</button></div>`;
          document.getElementById("rewardClose").onclick = () => { modal.hidden = true; };
        }
      }));
    });
  }

  function showReward(reward) {
    const modal = document.getElementById("rewardModal");
    const card = document.getElementById("rewardCard");
    card.innerHTML = `
      <h2>Well done, ${reward.profile}!</h2>
      <p class="reward-number">Sticker ${reward.position}</p>
      <div><img class="reward-image" src="${reward.image}" alt="${reward.category_label} reward sticker"></div>
      <p>Your new ${reward.category_label} sticker is saved in your sticker book.</p>
      <div class="site-actions">
        <button class="site-primary" id="rewardContinue" type="button">Back to the book</button>
        <a class="site-secondary" href="/stickers/">Open sticker book</a>
      </div>
    `;
    modal.hidden = false;
    document.getElementById("rewardContinue").onclick = () => {
      modal.hidden = true;
      document.getElementById("gameButton")?.focus();
    };
  }

  async function claimReward(rewardToken) {
    await ready;
    let result = await api("/api/rewards/claim", { method: "POST", body: JSON.stringify({ reward_token: rewardToken }) });
    if (result.parent_preview) return result;
    if (result.needs_choice) result = await chooseSticker(result.position, rewardToken);
    showReward(result);
    return result;
  }

  async function boot() {
    createInterface();
    document.getElementById("siteProfileButton").addEventListener("click", () => openProfileModal(false));
    document.getElementById("profileConfirm").addEventListener("click", confirmSwitch);
    document.getElementById("profilePinInput").addEventListener("keydown", event => {
      if (event.key === "Enter") confirmSwitch();
    });
    document.getElementById("profileCancel").addEventListener("click", () => {
      document.getElementById("profileModal").hidden = true;
    });
    try {
      const status = await api("/api/profile");
      profiles = status.profiles || profiles;
      parentProfile = status.parent_profile || profiles[0];
      childProfiles = status.child_profiles || profiles.slice(1);
      if (status.profile) {
        setProfile(status.profile);
        resolveReady(status.profile);
      } else {
        openProfileModal(true);
      }
    } catch (error) {
      document.getElementById("profileError").textContent = "The profile service is not ready. Refresh the page in a moment.";
      openProfileModal(true);
    }
  }

  window.ProfileShell = Object.freeze({
    ready,
    claimReward,
    get parentProfile() { return parentProfile; },
    get childProfiles() { return [...childProfiles]; },
    get profile() { return profile; }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
