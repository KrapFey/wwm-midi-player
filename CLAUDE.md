# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A Windows-only desktop MIDI player with two playback modes:

1. **Audio mode** — plays MIDI through a bundled SoundFont (`TOH.sf2`, ~420MB, tracked via Git LFS)
   using `tinysoundfont`, so you hear the music through your speakers like a normal player.
2. **WWM mode** — plays MIDI by simulating keypresses into the game window "Where Winds Meet"
   (via `win32api`/`win32gui`), mapping MIDI notes to the game's in-game instrument (Konghou) key
   bindings, so the game character performs the song live. **This is the actual reason the
   project exists** — the audio player is really a secondary/preview feature.

The UI is HTML/CSS/JS in a native WebView2 window via `pywebview`, on a Python backend. It can't be
a plain website: WWM mode needs Windows APIs (window lookup, `PostMessage`, global hotkeys), so
Python owns all logic and timing and the page only renders. Features on top of playback: a
falling-note piano visualizer (colored per MIDI track), per-track mute/solo, skins, per-song
transpose + WWM playable-range view, song details, drag & drop, an always-on-top mini player.

Packaged as a standalone Windows `.exe` via PyInstaller (`app.spec` → `dist/`).

## Commands

```bash
python src/web_app.py       # run the app from source
python src/web_preview.py   # serve the UI to a normal browser with a mock backend (UI work)
python -m pytest            # run the test suite
ruff check                  # lint (strict ruleset — see pyproject.toml)
ruff format                 # format
pre-commit run --all-files  # end-of-file-fixer, trailing-whitespace, check-merge-conflict, ruff-check --fix
```

Run a single test: `python -m pytest tests/test_midi_timing.py::test_name`

Environment setup uses [uv](https://docs.astral.sh/uv/): `uv venv --seed` then
`uv pip install -e ".[dev]"` (see README.md/CONTRIBUTING.md). The `.venv` here was created with
`uv venv`, not plain `venv`.

**Important:** `pre-commit`'s hook only runs `ruff check --fix`, **not** `ruff format`. The
codebase's actual style (e.g. `Type|None` with no spaces around `|`) does not match what
`ruff format` would produce — do not run `ruff format` broadly across files you didn't
intentionally rewrite, or you'll generate large, unrelated reformatting diffs.

Build the Windows installer: `./build-installer.ps1` (drives PyInstaller via `app.spec`, then
Inno Setup via `installer.iss`).

## Tech stack

- Python 3.11–3.13 (`pyproject.toml` caps `<3.14` because `pyaudio`, a transitive dependency of
  `tinysoundfont`, has no prebuilt Windows wheel for 3.14 yet)
- `pywebview` (Edge WebView2, via `pythonnet`) for the window; plain HTML/CSS/ES-module JS for the
  UI — no Node toolchain or build step
- `mido` for MIDI file parsing, `tinysoundfont` for SoundFont audio synthesis
- `keyboard` for global hotkeys (F8/F9/F10/F11), `pywin32` for Windows window messaging
  (`win32gui`/`win32api`/`win32con`) — the app is Windows-only, no cross-platform fallback paths
- `ruff` for lint/format, `pre-commit` hooks, `pyinstaller` for packaging, `pytest` for tests

## Layout

```
src/web_app.py             Entry point (main(), also the `wwm-player` console script): Desktop -
                            pywebview windows, native dialogs, Explorer, drag & drop, mini player
                            (implements web.api.Shell) + F8-F11 global hotkeys
src/web_preview.py         Dev server: the UI in a browser with a mock backend (js/mock.js)
src/web/api.py             Api - the JS-callable backend: all player state (playlist, transport,
                            seek, volume, mode, mute/solo, transpose, details, skins, settings,
                            keybindings); pushes events to the page(s) (tested)
src/web/static/            UI: index.html + mini.html (always-on-top mini player), css/app.css
                            (skins as CSS variables + data-glass/data-hud/data-glow attributes),
                            js/ (app, mini, bridge, skin, clock, visualizer canvas, slider, color,
                            mock) - plain ES modules
src/utils/playback_engine.py  PlaybackEngine - the real-time playback loop (callbacks, run on a
                            thread by Api) + create_synth() (tested)
src/utils/midi_timing.py   Pure tempo-map / tick-to-seconds duration math, TickClock (incremental
                            per-track tick→seconds converter shared by note_events.py and
                            playback_stream.py) (tested)
src/utils/note_events.py   build_note_events() — precomputes all note on/off events per track for
                            the visualizer; summarize_tracks()/extract_track_names()/TrackSummary
                            for the mute/solo panel (tested)
src/utils/playback_stream.py  build_playback_messages() — track-tagged, time-sorted message
                            stream that drives live playback (see "How playback works") (tested)
src/utils/playlist.py      Pure playlist logic: shuffle/repeat navigation, index bookkeeping for
                            remove/reorder, folder expansion, .m3u read/write (tested)
src/utils/song_analysis.py Pure per-song analysis: duration, track count, WWM playable fraction,
                            best_transpose() for auto-fit (tested)
src/utils/skins.py         Pure skin registry: Skin/PianoColors, SKINS (Default, Cyberpunk,
                            Neon Glass),
                            PALETTE_KEYS, CHANNEL_COLORS (default note palette) (tested)
src/utils/piano_layout.py  Pure 88-key keyboard geometry (white/black key positions) (tested)
src/utils/app_settings.py  Persisted settings (volume, mode, playlist, selection, theme, skin,
                            per-song transpose) as JSON, loaded on launch, saved on close (tested)
src/utils/track_info.py    Track metadata extraction (artist/title from filename) (tested)
src/utils/wwm_macro.py     KeyManager (Singleton) — note→key mapping, keybinding persistence,
                            Windows PostMessage-based key injection into the game window (tested)
src/utils/resources.py     resource_path() (source tree vs. PyInstaller bundle) + Singleton (tested)
src/input/keybindings.json User's saved keybinding overrides (gitignored)
src/input/settings.json    User's saved app settings (gitignored)
src/input/logo.ico         App icon
TOH.sf2                    Bundled SoundFont (~420MB, tracked via Git LFS — see "Known rough edges")
app.spec                   PyInstaller build spec
installer.iss              Inno Setup installer script
build-installer.ps1        Drives PyInstaller + Inno Setup build
docs/screenshots/          README screenshots (taken from web_preview.py - see "Testing")
tests/                     pytest suite for the Python modules above
```

## Architecture: Python backend, page renders

- **All player logic and state live in Python.** `web.api.Api` holds the state; the page renders
  `Api.get_state()` and forwards input by calling Api methods. pywebview exposes every *public*
  method of `Api` to JS as `window.pywebview.api.<name>()` (a Promise) — keep internals private
  (`__name`), since public attributes/methods are reachable from the page.
- **Python → page** goes through an injected `emit(event, payload)`; `web_app.Desktop.emit`
  evaluates `window.app.onEvent(name, payload)` in every open window (main + mini player). Events:
  `state`, `details`, `duration`, `clock`, `notes`, `tracks`, `error`, `status`.
- **Timing never moves to JS.** Browsers throttle background timers, and in WWM mode the game has
  focus. The page animates from a clock snapshot (`{position, playing}` pushed on changes and
  resynced every second by `get_clock()`; `js/clock.js`) instead of per-frame IPC.
- **Threading:** pywebview calls Api methods on worker threads, hotkeys on the `keyboard` hook
  thread, engine callbacks arrive on the playback thread. Public methods serialize on one
  `RLock`. Engine callbacks and the song-analysis worker must **not** take it (the lock holder may
  be joining the playback thread in `__stop_engine`) — they only swap in fresh objects and emit.
- **Anything needing real windows** (file dialogs, Explorer, the mini player window) goes through
  the injected `Shell` protocol — `web_app.Desktop` in the app, fakes in tests — so `Api` is fully
  testable without pywebview.
- **Local pages:** `web_app.py` passes `web/static/index.html`, relative to the entry script's
  folder (or the PyInstaller bundle root); pywebview serves such paths over its built-in HTTP
  server, which ES modules require (they won't load from `file://`). `app.spec` must bundle
  `src/web/static` at exactly `web/static`.
- **Icon:** `webview.start(icon=...)` sets every window's icon (pywebview's docstring says
  GTK/QT only, but its WinForms backend honors it; without it the icon comes from the running
  executable — `python.exe` from source). `main()` also sets an explicit AppUserModelID first, or
  the taskbar groups a from-source run under Python and shows Python's icon.
- **Drag & drop:** page JS never sees real file paths. `Desktop` registers a Python DOM `drop`
  handler, which gets `pywebviewFullPath` per file and calls `Api.add_paths` (folders expanded);
  JS only shows the overlay. Internal song reordering uses its own drag type
  (`application/x-wwm-song`) and is handled in JS.

## How playback works (src/utils/playback_engine.py)

- `PlaybackEngine` owns one MIDI file's playback; `Api.__start` runs `engine.run()` on a daemon
  `threading.Thread`. On start it computes duration (`utils.midi_timing.calculate_duration`),
  precomputes `utils.note_events.build_note_events()` (`on_notes`, feeds the visualizer) and
  `summarize_tracks()` (`on_tracks`, feeds the mute/solo panel), then builds
  `utils.playback_stream.build_playback_messages()` — a single track-tagged, time-sorted list of
  every `note_on`/`note_off`/`control_change`/`program_change` message. The real-time loop
  iterates that list directly (not mido's own merged real-time iterator, which discards which
  track a message came from — track identity is required for per-track muting), using
  `time.perf_counter()` for timing.
- Note events within the same tick are batched into "chords" (`__flush_tick_events`) so
  simultaneous notes fire together rather than one at a time. `note_on` is filtered per-message
  against `__muted_tracks` (a `frozenset[int]`, swapped by reference via `set_muted_tracks()` —
  same lock-free pattern as `__running`/`__paused`/`__volume`); `note_off` is always forwarded so
  an already-sounding note rings out to its own length instead of hanging if its track gets muted
  mid-note.
- In audio mode, notes go to `tinysoundfont.Synth`; in WWM mode, they go to
  `KeyManager.play_chord`, which maps each MIDI note (folded into a 48–83 playable range) to a
  keybinding and posts synthetic key events to the game window via `win32api`.
- `transpose` shifts every note (both modes, so Audio previews what WWM plays) and the note events
  reported to `on_notes`. Api passes the song's saved transpose; changing it while playing
  restarts the engine at the current position (keeping a pause).
- Volume: the UI slider is a *master* multiplier, not a raw MIDI CC7 override —
  `__channel_base_volume` tracks each channel's own file-authored CC7 value (GM default 100), and
  the slider scales that (`base * slider // 127`) so a track's own mix balance isn't clobbered.
  `create_synth()` builds the shared synth with `SYNTH_GAIN_DB = -6.0` headroom (no clipping on
  dense chords) and `max_voices=1024` (no audible voice-stealing on dense files); Api creates it
  once, lazily, since loading the SoundFont is the slow part.
- Seeking restarts the engine with `start_offset`; `run()` fast-forwards through the message
  stream up to that point (still applying program/control changes, muting audible output) before
  resuming real-time playback. Pause/resume adjusts `start_time` by the paused duration.
- `elapsed_seconds()` is the single source of truth for position (Api's `get_clock()` reads it);
  it reports `start_offset` until `run()` has parsed the file and anchored its clock. After the
  thread exits, `get_clock()` reports 0 (an errored engine's clock would keep counting).
- `run()` wraps parsing and the playback loop in broad exception handlers, reporting failures via
  `on_error` (shown as a toast) instead of the thread dying silently.
- `on_ended` fires only when a song finishes on its own and drives auto-advance (on a fresh
  thread, since advancing joins the playback thread); Next/auto-advance/repeat/shuffle all go
  through `utils.playlist.next_track_index()`. Mute/solo state resets when a *different* song
  starts but persists across a seek/transpose restart of the same song (`Api.__change_song`).

## Visualizer (src/web/static/js/visualizer.js)

Canvas port with key geometry from `Api.get_piano_layout()` (the tested `utils.piano_layout`
math, normalized to width 1.0). Notes are colored per **originating MIDI track**
(`noteColor` in `js/color.js`), not per channel — many real-world files route every instrument
through the same channel and differentiate instruments by track instead. `js/color.js`'s
`lighter`/`darker` implement Qt's `QColor.lighter/darker` HSV semantics (kept from the original Qt
UI) and are memoized, since every note is shaded every frame. Only *sounding* notes glow on
neon-glow skins (glowing every bar was the costliest part of a frame on dense songs). In WWM mode
(`setRange`), keys outside 48–83 are dimmed, out-of-range notes drawn faded/dashed, and the key
each sounding out-of-range note folds onto is outlined (`foldNote` mirrors
`utils.wwm_macro.fold_note`).

## Skins & themes (src/utils/skins.py, js/skin.js, css/app.css)

A `Skin` bundles everything visual that varies: a palette per variant (`"dark"`/`"light"`) with
exactly `PALETTE_KEYS`, 16 note colors, piano key colors, corner radii (`radius_sm/md`),
body/heading/mono font families, and three effect flags. `get_state()` sends every skin;
`js/skin.js#applySkin` turns the active one into CSS variables (`ACCENT_1` → `--accent-1`,
fonts as fallback stacks, radii) and sets attributes on `<html>` that `css/app.css` targets:
`data-skin="<key>"` for one skin's own block (e.g. the whole Night City look is
`[data-skin="cyberpunk"]` rules at the end of `app.css` — chamfers, glitch, scanlines), plus
shared effect flags any skin can opt into:

- `neon_glow` — soft outer glows (`box-shadow`/`text-shadow`/`drop-shadow`; canvas `shadowBlur`).
- `glass` — lit backdrop, translucent `backdrop-filter` cards, rounded visualizer card.
- `hud` — segmented LED progress/volume bars (one CSS mask over track and fill; the glow sits on
  the unmasked parent, since a mask clips an element's own shadow), telemetry grid + live readout
  chips in the visualizer, PLAYING/STANDBY + AUDIO/WWM status chips, uppercase mono captions.

Night City notes: panels are chamfered with `clip-path`, which would cut off a normal border
along the diagonals, so a panel's frame color is its own background and its face is a 1px-inset
`::before` clipped to the same shape (`--chamfer` / `--chamfer-inner`); clip-path also clips an
element's own shadows, so glows go on an unclipped parent (`filter: drop-shadow`). The title
glitch layers read the title from `data-text` (kept in sync by `skin.js#setTitle`, which also
restarts the `.flicker` animation on change). Its animations are disabled under
`prefers-reduced-motion`. Bahnschrift is variable, so `font-stretch` condenses it.

Category colors are palette roles, not raw accents: `ACCENT_1` playback, `VOLUME` volume and
track on/off switches, `MODE` the Audio/WWM toggle, `SOLO`, `RED`, with `HIGHLIGHT` as the shared
gradient tail. Skin and Dark/Light preference are independent: `Skin.resolve_variant()` renders a
dark-only skin (Cyberpunk, Neon Glass) dark while keeping the saved Light preference; the Theme toggle is
disabled for single-variant skins. Unknown skin/theme names fall back to defaults. To add a skin,
add it to `SKINS` with palettes defining exactly `PALETTE_KEYS` (enforced by `tests/test_skins.py`).

## Key mapping model (src/utils/wwm_macro.py)

Notes are described as scale degrees (`1`..`7`, plus sharps `#1/#4/#5` and flats `b3/b7`) across
three octave registers (`low`/`med`/`high`), matching the in-game instrument's 21-key layout
(QWERTY/ASDF/ZXCV rows). Default bindings mirror WWM's default Konghou keybinds. Users remap the
natural degrees in Settings → WWM keys (`Api.set_keybinding`: A–Z/0–9 only, no duplicates;
sharps/flats follow as Shift/Ctrl + that key), persisted to `src/input/keybindings.json`. On
load, `merge_keybindings()` overlays the saved file onto the defaults, so a missing/corrupt/
partial file falls back per-entry instead of crashing. `KeyManager` is a singleton that writes
the real file — tests inject a fake via `Api(key_manager=...)`.

## Settings persistence (src/utils/app_settings.py)

`AppSettings` (volume, Audio/WWM mode, playlist file paths, last-selected index, theme, skin,
per-song `transpose` map) is loaded in `Api.__init__` and saved in `Api.close()` (on main window
close), as JSON at `src/input/settings.json`. Restoring the last selection highlights the song but
deliberately does **not** mark it "now playing". Missing/corrupt settings files (or malformed
entries, e.g. in `transpose`) fall back to defaults safely — never crash on a bad user file.

## Testing

`pytest` (config in `pyproject.toml`, `pythonpath = ["src"]`) covers the Python side: the pure
`utils/` modules, `utils/playback_engine.py` (real-time runs of tiny MIDI files through a fake
synth), and `web/api.py` (no browser; fake synth, `FakeShell`, fake `KeyManager`, recorded
`emit`). Filesystem-touching tests are isolated via `tmp_path`/`monkeypatch.chdir`.

There are no automated tests for the HTML/CSS/JS. Check UI changes with `node --check` on the JS,
then `src/web_preview.py` + headless Edge screenshots:
`msedge --headless=new --window-size=1400,850 --virtual-time-budget=5000 --user-data-dir=<fresh
dir> --screenshot=<file> "http://127.0.0.1:8765/index.html?notransition&skin=cyberpunk"`. Use a
fresh `--user-data-dir` per run (cached JS otherwise) and `?notransition` (headless capture can
freeze CSS transitions mid-way). Headless also enforces a ~500px minimum viewport, crops narrower
captures, and barely advances `requestAnimationFrame` timestamps. `js/mock.js` documents URL
parameters that set up views (`?tab=`, `?wwm`, `?solo=`, `?click=<id>`, `?contextmenu=<n>`,
`?keys`, `?error=<text>`, `?animtime=<ms>` to freeze CSS animations at a moment, since
headless capture doesn't advance them; `mini.html` for the mini player). The real JS↔Python bridge can be
smoke-tested with `hidden=True` pywebview windows and `evaluate_js` (point `Api` at a temp
`settings_path` so the user's real settings aren't touched).

## Known rough edges

- `git log` messages in this repo are frequently uninformative (e.g. literally "Description:") —
  read the diffs directly if you need history context.
- `ruff` config in `pyproject.toml` is strict (docstrings required via `D`/pydocstyle Google
  convention, `PTH`, `ARG`, `COM`, etc.) — run `ruff check` before committing. Do **not** run
  `ruff format` broadly (see "Commands" above — pre-commit only enforces `ruff check --fix`, and
  the codebase's actual style disagrees with `ruff format`'s output).
  `tests/*` is exempted from docstring rules via `per-file-ignores`.
- The built `.exe` requests admin (`uac_admin=True` in `app.spec`, needed to post keys to the
  game) — launching it shows a UAC prompt.
- Large binary artifacts live in the repo root: `TOH.sf2` (~420MB, Git LFS) and any built `.exe`
  (untracked build output) — be mindful of these when doing repo-wide operations; cloning/diffing
  is noticeably heavier than a typical Python repo because of this file.
