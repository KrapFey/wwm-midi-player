// Mock backend for developing the UI in a plain browser (see src/web_preview.py).
//
// Loads a snapshot of the real backend's state (real skins, piano layout, and
// demo notes) from /mock-state.json and fakes just enough behavior to click
// around. URL parameters override the snapshot, which is handy for screenshots:
//   ?skin=cyberpunk&theme=light   skin / theme
//   ?tab=tracks                   open a sidebar tab
//   ?wwm                          WWM mode (shows the playable-range overlay)
//   ?click=<element id>           click a control, e.g. open-settings
//   ?contextmenu=<song index>     open a song's right-click menu
//   ?keys                         open the keybinding editor
//   ?solo=<track index>           solo one track
//   ?error=<text>                 show an error toast
//   ?notransition                 disable CSS transitions (headless capture
//                                 can otherwise freeze controls mid-animation)

export async function createMockApi(onEvent) {
  const snapshot = await (await fetch("/mock-state.json")).json();
  const params = new URLSearchParams(location.search);
  const state = snapshot.state;
  state.skin = params.get("skin") ?? state.skin;
  state.theme = params.get("theme") ?? state.theme;
  if (params.has("wwm")) state.is_audio = false;
  if (params.has("solo")) {
    state.soloed = Number(params.get("solo"));
    state.muted = state.tracks.map((t) => t.index).filter((t) => t !== state.soloed);
  }
  let clock = { ...snapshot.clock };
  let bindings = structuredClone(snapshot.keybindings);
  if (params.has("notransition")) {
    const style = document.createElement("style");
    style.textContent = "*, *::before, *::after { transition: none !important; }";
    document.head.append(style);
  }
  const emit = (name, payload) => setTimeout(() => onEvent(name, payload), 0);
  const snapshotState = () => structuredClone(state);

  setTimeout(() => {
    emit("duration", { seconds: state.duration });
    emit("notes", { notes: snapshot.notes });
    emit("clock", clock);
    if (params.get("tab")) document.querySelector(`[data-tab="${params.get("tab")}"]`)?.click();
    if (params.get("click")) document.getElementById(params.get("click"))?.click();
    if (params.has("keys")) document.getElementById("open-keys")?.click();
    if (params.has("contextmenu")) {
      const song = document.querySelectorAll(".song")[Number(params.get("contextmenu"))];
      const rect = song?.getBoundingClientRect();
      song?.dispatchEvent(new MouseEvent("contextmenu", {
        bubbles: true, clientX: rect.left + 120, clientY: rect.top + 20 }));
    }
    if (params.get("error")) {
      clock = { position: 0, playing: false };
      emit("error", { message: params.get("error") });
    }
  }, 50);

  const mute = () => ({ muted: state.muted, soloed: state.soloed });
  const focus = () => state.files[state.now_playing >= 0 ? state.now_playing : state.current];
  return {
    get_state: async () => snapshotState(),
    get_clock: async () => clock,
    get_piano_layout: async () => snapshot.layout,
    add_files: async () => snapshotState(),
    clear_playlist: async () => ({ ...snapshotState(), files: [], current: -1, now_playing: -1 }),
    load_playlist: async () => snapshotState(),
    save_playlist: async () => true,
    remove_file: async (index) => {
      state.files.splice(index, 1);
      return snapshotState();
    },
    move_file: async (source, target) => {
      state.files.splice(target, 0, ...state.files.splice(source, 1));
      return snapshotState();
    },
    reveal_file: async () => {},
    play_index: async (index) => {
      state.current = state.now_playing = index;
      emit("state", snapshotState());
    },
    play_pause: async () => {
      state.paused = !state.paused;
      clock = { position: clock.position, playing: !state.paused };
      emit("clock", clock);
      emit("state", snapshotState());
    },
    next_track: async () => {},
    previous_track: async () => {},
    seek: async (seconds) => { clock = { position: seconds, playing: clock.playing }; emit("clock", clock); },
    set_transpose: async (semitones) => {
      focus().transpose = Math.max(-24, Math.min(24, semitones));
      return snapshotState();
    },
    auto_transpose: async () => snapshotState(),
    set_volume: async (value) => { state.volume = value; },
    set_audio_mode: async (isAudio) => { state.is_audio = isAudio; emit("state", snapshotState()); },
    set_shuffle: async () => {},
    set_repeat: async () => {},
    set_skin: async (name) => { state.skin = name; },
    set_theme: async (name) => { state.theme = name; },
    toggle_mini_player: async () => { window.open(`mini.html${location.search}`, "_blank", "width=400,height=136"); },
    show_main_window: async () => {},
    get_keybindings: async () => ({ bindings, defaults: snapshot.keybindings }),
    set_keybinding: async (octave, degree, key) => {
      bindings[octave][degree] = key.toUpperCase();
      return { ok: true, error: "", bindings };
    },
    reset_keybindings: async () => {
      bindings = structuredClone(snapshot.keybindings);
      return { bindings, defaults: snapshot.keybindings };
    },
    set_track_enabled: async (track, enabled) => {
      state.soloed = null;
      state.muted = enabled ? state.muted.filter((t) => t !== track) : [...state.muted, track];
      return mute();
    },
    solo_track: async (track, soloed) => {
      state.soloed = soloed ? track : null;
      state.muted = soloed ? state.tracks.map((t) => t.index).filter((t) => t !== track) : [];
      return mute();
    },
  };
}
