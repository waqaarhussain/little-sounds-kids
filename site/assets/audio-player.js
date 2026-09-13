(function () {
  "use strict";

  const player = new Audio();
  player.preload = "auto";
  player.playsInline = true;
  let currentSource = "";

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
    player.src = source;
    player.currentTime = 0;
    try {
      await player.play();
      return true;
    } catch (error) {
      console.warn("Audio playback was blocked or failed:", source, error);
      return false;
    }
  }

  function preload(sources) {
    sources.filter(Boolean).forEach(source => {
      const audio = new Audio();
      audio.preload = "metadata";
      audio.src = source;
    });
  }

  window.SiteAudio = Object.freeze({
    play,
    stop,
    preload,
    get currentSource() {
      return currentSource;
    }
  });
})();
