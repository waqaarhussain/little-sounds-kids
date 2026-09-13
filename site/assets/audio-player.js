(function () {
  "use strict";

  const AUDIO_VERSION = "20260913-uk3";
  const player = new Audio();
  player.preload = "auto";
  player.playsInline = true;
  const unlockPlayer = new Audio("data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACAgICA");
  unlockPlayer.playsInline = true;
  let currentSource = "";
  let unlocked = false;
  let muted = localStorage.getItem("little-sounds-muted") === "true";

  function versioned(source) {
    if (!source || !source.startsWith("/audio/")) return source;
    return `${source}${source.includes("?") ? "&" : "?"}v=${AUDIO_VERSION}`;
  }

  function stop() {
    player.pause();
    player.removeAttribute("src");
    player.load();
    currentSource = "";
  }

  async function play(source) {
    if (!source || muted) return false;
    stop();
    currentSource = source;
    player.src = versioned(source);
    player.currentTime = 0;
    try {
      await player.play();
      return true;
    } catch (error) {
      console.warn("Audio playback was blocked or failed:", source, error);
      return false;
    }
  }

  function setMuted(value) {
    muted = Boolean(value);
    localStorage.setItem("little-sounds-muted", String(muted));
    if (muted) stop();
    window.dispatchEvent(new CustomEvent("siteaudiochange", { detail: { muted } }));
    return muted;
  }

  function unlock() {
    if (unlocked) return;
    unlockPlayer.volume = 0.01;
    const promise = unlockPlayer.play();
    if (promise && typeof promise.then === "function") {
      promise.then(() => {
        unlockPlayer.pause();
        unlockPlayer.currentTime = 0;
        unlocked = true;
      }).catch(() => {});
    }
  }

  function preload(sources) {
    sources.filter(Boolean).forEach(source => {
      const audio = new Audio();
      audio.preload = "metadata";
      audio.src = versioned(source);
    });
  }

  window.SiteAudio = Object.freeze({
    play,
    unlock,
    stop,
    preload,
    setMuted,
    toggleMuted() { return setMuted(!muted); },
    isMuted() { return muted; },
    get currentSource() {
      return currentSource;
    }
  });
})();
