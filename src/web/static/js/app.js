// WWM MIDI Player web UI: renders backend state and forwards user actions.
//
// All player logic lives in Python (web/api.py -> utils/*). This module only
// renders `state` (Api.get_state()), applies push events from the backend, and
// animates playback locally from a clock snapshot (see clock.js), so no
// per-frame IPC is needed.

import { connectBackend } from "./bridge.js";
import { Clock, formatTime } from "./clock.js";
import { noteColor } from "./color.js";
import { activeSkin, applySkin, setTitle } from "./skin.js";
import { Slider } from "./slider.js";
import { Visualizer } from "./visualizer.js";

const CLOCK_RESYNC_MS = 1000;
const TELEMETRY_INTERVAL_MS = 100;
const TOAST_MS = 5000;
const SEEK_STEP_SECONDS = 5;
const VOLUME_STEP = 8;
const SONG_DRAG_TYPE = "application/x-wwm-song";
const NATURAL_DEGREES = ["1", "2", "3", "4", "5", "6", "7"];
const OCTAVES = [["high", "High"], ["med", "Medium"], ["low", "Low"]];
// Keys that are shortcuts only together with Ctrl; every other shortcut is Ctrl-free.
const CTRL_SHORTCUTS = new Set(["o", "s"]);

const $ = (id) => document.getElementById(id);

let api;
let state;
let visualizer;
let progress;
let volume;
let selected = -1;
let menuIndex = -1;
let lastSecond = -1;
let lastTelemetry = -Infinity;  // so the first frame fills the HUD readouts
let toastTimer = 0;
let songsRenderQueued = false;
let keyBindings = null;
let capturing = null;  // {octave, degree} while the key editor waits for a key
const clock = new Clock();

// ---- Helpers --------------------------------------------------------------

/** The song the Tracks pane / transpose controls act on: now playing, else selected. */
const focusIndex = () => (state.now_playing >= 0 ? state.now_playing : state.current);
const focusFile = () => state.files[focusIndex()];
const position = () => clock.position(state.duration);

function applyState(next) {
  state = next;
  if (selected < 0 || selected >= state.files.length || state.now_playing >= 0) selected = state.current;
  render();
}

function refreshSkin() {
  const { skin, palette } = applySkin(state);
  visualizer.setSkin(skin, palette);
  renderTracks();
  renderSettings();
}

// ---- Rendering ------------------------------------------------------------

function render() {
  renderSongs();
  renderNowPlaying();
  renderTracks();
  renderSongTools();
  visualizer.setRange(state.is_audio ? null : state.wwm_range);
}

/** Coalesce bursts of per-song "details" events into one list render per frame. */
function queueRenderSongs() {
  if (songsRenderQueued) return;
  songsRenderQueued = true;
  requestAnimationFrame(() => {
    songsRenderQueued = false;
    renderSongs();
  });
}

function rangeClass(fraction) {
  return fraction >= 0.95 ? "good" : fraction >= 0.8 ? "fair" : "poor";
}

function renderSongs() {
  const list = $("song-list");
  const needle = $("search").value.trim().toLowerCase();
  list.replaceChildren(...state.files.flatMap((file, index) => {
    if (needle && !`${file.artist} ${file.title}`.toLowerCase().includes(needle)) return [];
    const item = document.createElement("li");
    item.className = "song";
    item.draggable = true;
    item.dataset.index = index;
    item.classList.toggle("selected", index === selected);
    item.classList.toggle("playing", index === state.now_playing);
    item.innerHTML = `<span class="glyph">&#9654;</span><span class="title"></span>
      <span class="details"></span><span class="artist"></span>`;
    item.querySelector(".title").textContent = file.title;
    item.querySelector(".artist").textContent = file.artist;
    item.querySelector(".details").replaceChildren(...songDetails(file));
    item.title = file.path;
    return [item];
  }));
  $("empty-songs").classList.toggle("hidden", state.files.length > 0);
}

/** Duration · track count · WWM-range badge, once the backend has analyzed the file. */
function songDetails(file) {
  if (file.duration === null) return [];
  const text = document.createElement("span");
  text.textContent = `${formatTime(file.duration)} · ${file.tracks} tr`;
  const badge = document.createElement("span");
  badge.className = `range-badge ${rangeClass(file.in_range)}`;
  badge.textContent = `${Math.round(file.in_range * 100)}%`;
  badge.title = `${Math.round(file.in_range * 100)}% of notes are inside WWM's playable range`
    + (file.transpose ? ` (transposed ${file.transpose > 0 ? "+" : ""}${file.transpose})` : "");
  return [text, badge];
}

function renderNowPlaying() {
  const file = focusFile();
  setTitle($("np-title"), file ? file.title : "No files loaded");
  $("np-artist").textContent = file ? file.artist : "";
  const playing = state.playing && !state.paused;
  $("play").classList.toggle("playing", playing);
  const status = $("chip-status");
  status.textContent = playing ? "● PLAYING" : state.paused ? "● PAUSED" : "● STANDBY";
  status.classList.toggle("live", playing);
  $("chip-mode").textContent = state.is_audio ? "AUDIO" : "WWM";
  $("mode").checked = state.is_audio;
  $("shuffle").classList.toggle("active", state.shuffle);
  $("repeat").classList.toggle("active", state.repeat);
  $("mini-player").classList.toggle("active", state.mini_open);
  progress.max = state.duration;
  volume.set(state.volume);
}

function renderSongTools() {
  const file = focusFile();
  for (const id of ["transpose-down", "transpose-up", "transpose-auto"]) $(id).disabled = !file;
  const shift = file ? file.transpose : 0;
  $("transpose-value").textContent = shift > 0 ? `+${shift}` : String(shift);
  const fraction = file?.in_range;
  $("range-fill").style.width = fraction == null ? "0" : `${fraction * 100}%`;
  $("range-fill").className = fraction == null ? "" : rangeClass(fraction);
  $("range-value").textContent = fraction == null ? "–" : `${Math.round(fraction * 100)}%`;
}

function renderTracks() {
  const skin = activeSkin(state);
  const list = $("track-list");
  const muted = new Set(state.muted);
  list.replaceChildren(...state.tracks.map((track) => {
    const row = document.createElement("li");
    row.className = "track";
    row.innerHTML = `<span class="swatch"></span><span class="name"></span>
      <button class="solo" title="Solo: mute every other track">S</button>
      <label class="switch"><input type="checkbox"><span></span></label>`;
    row.querySelector(".swatch").style.background = noteColor(skin.note_colors, track.index, track.is_drum);
    row.querySelector(".name").textContent = track.name;
    const solo = row.querySelector(".solo");
    solo.classList.toggle("active", state.soloed === track.index);
    solo.addEventListener("click", async () => {
      applyMute(await api.solo_track(track.index, state.soloed !== track.index));
    });
    const toggle = row.querySelector("input");
    toggle.checked = !muted.has(track.index);
    toggle.addEventListener("change", async () => {
      applyMute(await api.set_track_enabled(track.index, toggle.checked));
    });
    return row;
  }));
  $("empty-tracks").classList.toggle("hidden", state.tracks.length > 0);
  visualizer.setMuted(state.muted);
}

function applyMute({ muted, soloed }) {
  state.muted = muted;
  state.soloed = soloed;
  renderTracks();
}

function renderSettings() {
  const select = $("skin-select");
  select.replaceChildren(...Object.entries(state.skins).map(([key, skin]) => new Option(skin.display_name, key)));
  select.value = state.skin;
  const themeable = Object.keys(activeSkin(state).palettes).length > 1;
  $("theme").checked = state.theme === "light";
  $("theme").disabled = !themeable;
  $("theme-row").classList.toggle("disabled", !themeable);
}

function buildTelemetry() {
  const readouts = [["voices", "VOICES", "--green"], ["density", "NOTES/S", "--solo"],
    ["tracks", "TRACKS", "--mode"], ["range", "RANGE", "--highlight"], ["time", "T+", "--accent-1"]];
  $("telemetry").replaceChildren(...readouts.map(([key, label, color]) => {
    const chip = document.createElement("div");
    chip.className = "readout";
    chip.dataset.readoutChip = key;
    chip.style.setProperty("--readout-color", `var(${color})`);
    chip.innerHTML = `<i></i>${label} <b data-readout="${key}"></b>`;
    return chip;
  }));
}

function renderTelemetry(stats, seconds) {
  const minutes = Math.floor(seconds / 60);
  const inRange = focusFile()?.in_range;
  const values = {
    voices: String(stats.voices).padStart(2, "0"),
    density: stats.density.toFixed(1).padStart(4, "0"),
    tracks: String(stats.tracks).padStart(2, "0"),
    range: inRange == null ? "--" : `${Math.round(inRange * 100)}%`,
    time: `${String(minutes).padStart(2, "0")}:${(seconds - minutes * 60).toFixed(1).padStart(4, "0")}`,
  };
  for (const element of document.querySelectorAll("[data-readout]")) {
    element.textContent = values[element.dataset.readout];
  }
  // The range readout only means something in WWM mode.
  document.querySelector('[data-readout-chip="range"]').classList.toggle("hidden", state.is_audio);
}

function showToast(message, kind = "error") {
  $("toast-message").textContent = message;
  $("toast").classList.toggle("info", kind === "info");
  $("toast").classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.add("hidden"), TOAST_MS);
}

// ---- Backend events -------------------------------------------------------

function onEvent(name, payload) {
  if (!state) return;
  switch (name) {
    case "state": {
      const skinChanged = payload.skin !== state.skin || payload.theme !== state.theme;
      applyState(payload);
      if (skinChanged) refreshSkin();
      break;
    }
    case "details": {
      const index = state.files.findIndex((file) => file.path === payload.path);
      if (index >= 0) state.files[index] = payload;
      queueRenderSongs();
      renderSongTools();
      break;
    }
    case "duration":
      state.duration = payload.seconds;
      progress.max = payload.seconds;
      break;
    case "clock":
      clock.set(payload);
      break;
    case "notes":
      visualizer.load(payload.notes);
      lastTelemetry = -Infinity;  // refresh the HUD readouts on the next frame
      break;
    case "tracks":
      state.tracks = payload.tracks;
      applyMute(payload);
      break;
    case "error":
      // Nothing is playing any more: reset progress, like a fresh start.
      state.now_playing = -1;
      state.playing = false;
      state.duration = 0;
      progress.max = 0;
      lastSecond = -1;
      clock.set({ position: 0, playing: false });
      visualizer.clear();
      render();
      showToast(payload.message);
      break;
    case "status":
      showToast(payload.message, "info");
      break;
  }
}

// ---- Frame loop -----------------------------------------------------------

function frame(now) {
  // While scrubbing, the visualizer follows the drag before the seek commits.
  const seconds = progress.dragging ? progress.value : position();
  const stats = visualizer.render(seconds);
  progress.set(seconds);
  const second = Math.floor(seconds);
  if (second !== lastSecond) {
    lastSecond = second;
    $("time").textContent = `${formatTime(seconds)} / ${formatTime(state.duration)}`;
  }
  if (now - lastTelemetry > TELEMETRY_INTERVAL_MS) {
    lastTelemetry = now;
    renderTelemetry(stats, seconds);
  }
  requestAnimationFrame(frame);
}

// ---- Playlist actions -----------------------------------------------------

async function addFiles() {
  applyState(await api.add_files());
}

async function removeSong(index) {
  const wasPlaying = index === state.now_playing;
  applyState(await api.remove_file(index));
  if (wasPlaying) visualizer.clear();
}

async function playlistAction(action, index) {
  if (action === "play") await api.play_index(index);
  else if (action === "reveal") await api.reveal_file(index);
  else if (action === "remove") await removeSong(index);
}

function openContextMenu(event, index) {
  event.preventDefault();
  menuIndex = index;
  selected = index;
  renderSongs();
  const menu = $("context-menu");
  menu.classList.remove("hidden");
  menu.style.left = `${Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 4)}px`;
  menu.style.top = `${Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 4)}px`;
}

function bindSongList() {
  const list = $("song-list");
  const songAt = (event) => event.target.closest(".song");
  list.addEventListener("click", (event) => {
    const song = songAt(event);
    if (!song) return;
    selected = Number(song.dataset.index);
    renderSongs();
  });
  list.addEventListener("dblclick", (event) => {
    const song = songAt(event);
    if (song) api.play_index(Number(song.dataset.index));
  });
  list.addEventListener("contextmenu", (event) => {
    const song = songAt(event);
    if (song) openContextMenu(event, Number(song.dataset.index));
  });
  // Drag to reorder. Internal drags carry SONG_DRAG_TYPE; file drops from
  // Explorer are handled by bindFileDrop and Python instead.
  const clearMarkers = () => {
    for (const song of list.querySelectorAll(".drop-before, .drop-after")) {
      song.classList.remove("drop-before", "drop-after");
    }
  };
  list.addEventListener("dragstart", (event) => {
    const song = songAt(event);
    if (!song) return;
    event.dataTransfer.setData(SONG_DRAG_TYPE, song.dataset.index);
    event.dataTransfer.effectAllowed = "move";
    song.classList.add("dragging");
  });
  list.addEventListener("dragend", () => {
    clearMarkers();
    list.querySelector(".dragging")?.classList.remove("dragging");
  });
  list.addEventListener("dragover", (event) => {
    const song = songAt(event);
    if (!song || !event.dataTransfer.types.includes(SONG_DRAG_TYPE)) return;
    event.preventDefault();
    const rect = song.getBoundingClientRect();
    clearMarkers();
    song.classList.add(event.clientY > rect.top + rect.height / 2 ? "drop-after" : "drop-before");
  });
  list.addEventListener("drop", async (event) => {
    const song = songAt(event);
    if (!song || !event.dataTransfer.types.includes(SONG_DRAG_TYPE)) return;
    event.preventDefault();
    event.stopPropagation();
    const source = Number(event.dataTransfer.getData(SONG_DRAG_TYPE));
    const after = song.classList.contains("drop-after");
    clearMarkers();
    // The index the moved song ends up at, once it's taken out of the list.
    let target = Number(song.dataset.index) + (after ? 1 : 0);
    if (source < target) target -= 1;
    applyState(await api.move_file(source, target));
  });
}

/** Show the "drop to add" overlay while files from Explorer are dragged over the window. */
function bindFileDrop() {
  let depth = 0;
  const isFileDrag = (event) => event.dataTransfer.types.includes("Files");
  window.addEventListener("dragenter", (event) => {
    if (!isFileDrag(event)) return;
    depth += 1;
    $("drop-overlay").classList.remove("hidden");
  });
  window.addEventListener("dragleave", (event) => {
    if (!isFileDrag(event)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) $("drop-overlay").classList.add("hidden");
  });
  window.addEventListener("dragover", (event) => {
    if (isFileDrag(event)) event.preventDefault();
  });
  // Python (web_app.py) receives the drop with full file paths and pushes the
  // new playlist as a "state" event; this only hides the overlay.
  window.addEventListener("drop", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    depth = 0;
    $("drop-overlay").classList.add("hidden");
  });
}

// ---- Keybinding editor ----------------------------------------------------

async function openKeyEditor() {
  $("settings").classList.add("hidden");
  keyBindings = (await api.get_keybindings()).bindings;
  $("keys-error").textContent = "";
  capturing = null;
  renderKeyEditor();
  $("keys-modal").classList.remove("hidden");
}

function closeKeyEditor() {
  capturing = null;
  $("keys-modal").classList.add("hidden");
}

function renderKeyEditor() {
  $("keys-grid").replaceChildren(...OCTAVES.flatMap(([octave, label]) => {
    const heading = document.createElement("div");
    heading.className = "caption keys-octave";
    heading.textContent = label;
    const keys = NATURAL_DEGREES.map((degree) => {
      const button = document.createElement("button");
      button.className = "keycap";
      const waiting = capturing?.octave === octave && capturing?.degree === degree;
      button.classList.toggle("capturing", waiting);
      button.innerHTML = "<small></small><b></b>";
      button.querySelector("small").textContent = degree;
      button.querySelector("b").textContent = waiting ? "…" : keyBindings[octave]?.[degree] ?? "?";
      button.addEventListener("click", () => {
        capturing = { octave, degree };
        $("keys-error").textContent = "";
        renderKeyEditor();
      });
      return button;
    });
    return [heading, ...keys];
  }));
}

async function captureKey(event) {
  event.preventDefault();
  if (event.key === "Escape") {
    capturing = null;
    renderKeyEditor();
    return;
  }
  if (event.key.length !== 1) return;  // ignore Shift/Ctrl/arrows etc.
  const result = await api.set_keybinding(capturing.octave, capturing.degree, event.key);
  $("keys-error").textContent = result.error;
  keyBindings = result.bindings;
  if (result.ok) capturing = null;
  renderKeyEditor();
}

// ---- Keyboard shortcuts ---------------------------------------------------

function setVolume(value) {
  state.volume = Math.max(0, Math.min(127, value));
  volume.set(state.volume);
  api.set_volume(state.volume);
}

const SHORTCUTS = {
  " ": () => api.play_pause(),
  ArrowLeft: () => state.playing && api.seek(Math.max(0, position() - SEEK_STEP_SECONDS)),
  ArrowRight: () => state.playing && api.seek(Math.min(state.duration, position() + SEEK_STEP_SECONDS)),
  ArrowUp: () => setVolume(state.volume + VOLUME_STEP),
  ArrowDown: () => setVolume(state.volume - VOLUME_STEP),
  Enter: () => selected >= 0 && api.play_index(selected),
  Delete: () => selected >= 0 && removeSong(selected),
  "/": () => $("search").focus(),
  m: () => api.toggle_mini_player(),
  o: () => addFiles(),
  s: async () => {
    if (await api.save_playlist()) showToast("Playlist saved.", "info");
  },
};

function onKeyDown(event) {
  if (capturing) {
    captureKey(event);
    return;
  }
  if (event.key === "Escape") {
    for (const id of ["settings", "context-menu"]) $(id).classList.add("hidden");
    if (!$("keys-modal").classList.contains("hidden")) closeKeyEditor();
    if (document.activeElement === $("search")) $("search").blur();
    return;
  }
  const typing = event.target.matches("input[type=search], input[type=text], select");
  if (typing || !$("keys-modal").classList.contains("hidden")) return;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const ctrl = event.ctrlKey || event.metaKey;
  if (!SHORTCUTS[key] || ctrl !== CTRL_SHORTCUTS.has(key)) return;
  event.preventDefault();
  SHORTCUTS[key]();
}

// ---- User input -----------------------------------------------------------

function bindUi() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      for (const other of document.querySelectorAll(".tab")) other.classList.toggle("active", other === tab);
      $("songs-pane").classList.toggle("hidden", tab.dataset.tab !== "songs");
      $("tracks-pane").classList.toggle("hidden", tab.dataset.tab !== "tracks");
    });
  }
  $("search").addEventListener("input", renderSongs);
  bindSongList();
  bindFileDrop();
  $("add-files").addEventListener("click", addFiles);
  $("load-playlist").addEventListener("click", async () => {
    applyState(await api.load_playlist());
    visualizer.clear();
  });
  $("save-playlist").addEventListener("click", SHORTCUTS.s);
  $("clear-playlist").addEventListener("click", async () => {
    applyState(await api.clear_playlist());
    selected = -1;
    visualizer.clear();
  });
  $("context-menu").addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    $("context-menu").classList.add("hidden");
    if (action) playlistAction(action, menuIndex);
  });
  $("play").addEventListener("click", () => api.play_pause());
  $("previous").addEventListener("click", () => api.previous_track());
  $("next").addEventListener("click", () => api.next_track());
  $("shuffle").addEventListener("click", () => {
    state.shuffle = !state.shuffle;
    api.set_shuffle(state.shuffle);
    renderNowPlaying();
  });
  $("repeat").addEventListener("click", () => {
    state.repeat = !state.repeat;
    api.set_repeat(state.repeat);
    renderNowPlaying();
  });
  $("mini-player").addEventListener("click", () => api.toggle_mini_player());
  $("mode").addEventListener("change", (event) => api.set_audio_mode(event.target.checked));
  $("transpose-down").addEventListener("click", async () => {
    applyState(await api.set_transpose((focusFile()?.transpose ?? 0) - 1));
  });
  $("transpose-up").addEventListener("click", async () => {
    applyState(await api.set_transpose((focusFile()?.transpose ?? 0) + 1));
  });
  $("transpose-auto").addEventListener("click", async () => applyState(await api.auto_transpose()));
  $("open-settings").addEventListener("click", (event) => {
    event.stopPropagation();
    // Drop down from the button, right-aligned to it.
    const button = event.currentTarget.getBoundingClientRect();
    $("settings").style.top = `${button.bottom + 6}px`;
    $("settings").style.left = `${button.right}px`;
    $("settings").classList.toggle("hidden");
  });
  document.addEventListener("click", (event) => {
    if (!$("settings").contains(event.target)) $("settings").classList.add("hidden");
    if (!$("context-menu").contains(event.target)) $("context-menu").classList.add("hidden");
  });
  $("skin-select").addEventListener("change", (event) => {
    state.skin = event.target.value;
    api.set_skin(state.skin);
    refreshSkin();
  });
  $("theme").addEventListener("change", (event) => {
    state.theme = event.target.checked ? "light" : "dark";
    api.set_theme(state.theme);
    refreshSkin();
  });
  $("open-keys").addEventListener("click", openKeyEditor);
  $("close-keys").addEventListener("click", closeKeyEditor);
  $("keys-modal").addEventListener("click", (event) => {
    if (event.target === $("keys-modal")) closeKeyEditor();
  });
  $("reset-keys").addEventListener("click", async () => {
    keyBindings = (await api.reset_keybindings()).bindings;
    capturing = null;
    $("keys-error").textContent = "";
    renderKeyEditor();
  });
  $("toast").addEventListener("click", () => $("toast").classList.add("hidden"));
  document.addEventListener("keydown", onKeyDown);
  progress = new Slider($("progress"), {
    onCommit: (seconds) => {
      if (state.files.length) {
        clock.set({ position: seconds, playing: clock.playing });
        api.seek(seconds);
      }
    },
    onHover: (seconds, x) => {
      const tip = $("seek-tip");
      tip.classList.toggle("hidden", seconds === null || !state.duration);
      if (seconds === null) return;
      tip.textContent = formatTime(seconds);
      tip.style.left = `${x}px`;
    },
  });
  volume = new Slider($("volume"), { max: 127, onInput: (value) => setVolume(Math.round(value)) });
}

async function init() {
  api = await connectBackend(onEvent);
  visualizer = new Visualizer($("visualizer"), await api.get_piano_layout());
  state = await api.get_state();
  selected = state.current;
  buildTelemetry();
  bindUi();
  refreshSkin();
  render();
  clock.set(await api.get_clock());
  setInterval(async () => clock.set(await api.get_clock()), CLOCK_RESYNC_MS);
  requestAnimationFrame(frame);
}

init();
