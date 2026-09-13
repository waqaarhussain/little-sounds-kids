(function () {
  "use strict";

  const AUDIO_VERSION = "20260913-uk2";
  const player = new Audio();
  player.preload = "auto";
  player.playsInline = true;
  const unlockPlayer = new Audio("data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACAgICA");
  unlockPlayer.playsInline = true;
  let currentSource = "";
  let unlocked = false;

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
    if (!source) return false;
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
    get currentSource() {
      return currentSource;
    }
  });
})();
