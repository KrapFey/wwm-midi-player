// Mini player: a compact always-on-top controller window (opened by
// Api.toggle_mini_player). It shares the main window's backend Api object,
// so both stay in sync through the same pushed events.

import { connectBackend } from "./bridge.js";
import { Clock, formatTime } from "./clock.js";
import { applySkin, setTitle } from "./skin.js";
import { Slider } from "./slider.js";

const CLOCK_RESYNC_MS = 1000;
const $ = (id) => document.getElementById(id);

let api;
let state;
let progress;
let lastSecond = -1;
const clock = new Clock();

function render() {
  const index = state.now_playing >= 0 ? state.now_playing : state.current;
  const file = state.files[index];
  setTitle($("np-title"), file ? file.title : "No files loaded");
  $("np-artist").textContent = file ? file.artist : "";
  $("play").classList.toggle("playing", state.playing && !state.paused);
  $("chip-mode").textContent = state.is_audio ? "AUDIO" : "WWM";
  progress.max = state.duration;
}

function onEvent(name, payload) {
  if (!state) return;
  if (name === "state") {
    const skinChanged = payload.skin !== state.skin || payload.theme !== state.theme;
    state = payload;
    if (skinChanged) applySkin(state);
    render();
  } else if (name === "duration") {
    state.duration = payload.seconds;
    progress.max = payload.seconds;
  } else if (name === "clock") {
    clock.set(payload);
  } else if (name === "error") {
    state.duration = 0;
    clock.set({ position: 0, playing: false });
  }
}

function frame() {
  const seconds = clock.position(state.duration);
  progress.set(seconds);
  if (Math.floor(seconds) !== lastSecond) {
    lastSecond = Math.floor(seconds);
    $("time").textContent = `${formatTime(seconds)} / ${formatTime(state.duration)}`;
  }
  requestAnimationFrame(frame);
}

async function init() {
  api = await connectBackend(onEvent);
  state = await api.get_state();
  progress = new Slider($("progress"), {
    onCommit: (seconds) => {
      clock.set({ position: seconds, playing: clock.playing });
      api.seek(seconds);
    },
  });
  $("play").addEventListener("click", () => api.play_pause());
  $("previous").addEventListener("click", () => api.previous_track());
  $("next").addEventListener("click", () => api.next_track());
  $("expand").addEventListener("click", () => api.show_main_window());
  $("close").addEventListener("click", () => api.toggle_mini_player());
  applySkin(state);
  render();
  await clock.resync(() => api.get_clock());
  setInterval(() => clock.resync(() => api.get_clock()), CLOCK_RESYNC_MS);
  requestAnimationFrame(frame);
}

init();
