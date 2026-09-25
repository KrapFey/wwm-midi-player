# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A Windows-only desktop MIDI player (PySide6 GUI) with two playback modes:

1. **Audio mode** — plays MIDI through a bundled SoundFont (`TOH.sf2`, ~420MB, tracked via Git LFS)
   using `tinysoundfont`, so you hear the music through your speakers like a normal player.
2. **WWM mode** — plays MIDI by simulating keypresses into the game window "Where Winds Meet"
   (via `win32api`/`win32gui`), mapping MIDI notes to the game's in-game instrument (Konghou) key
   bindings, so the game character performs the song live. **This is the actual reason the
   project exists** — the audio player is really a secondary/preview feature.

On top of playback, the app has a falling-note piano visualizer (colored per MIDI track) and a
per-track mute/solo panel, both driven by the same track-aware note data.

Packaged as a standalone Windows `.exe` via PyInstaller (`app.spec` → `dist/`).

## Commands

```bash
python src/app.py           # run the app from source
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
- PySide6 (Qt) for UI, `mido` for MIDI file parsing, `tinysoundfont` for SoundFont audio synthesis
- `keyboard` for global hotkeys (F8/F9/F10/F11), `pywin32` for Windows window messaging
  (`win32gui`/`win32api`/`win32con`) — the app is Windows-only, no cross-platform fallback paths
- `ruff` for lint/format, `pre-commit` hooks, `pyinstaller` for packaging, `pytest` for tests

## Layout

```
src/app.py                 Entry point (main(), also the `wwm-player` console script) + Player
                            (QMainWindow) + Worker (QThread playback engine)
src/ui/                    Widgets: buttons/ (play, next, previous, shuffle, repeat, key,
                            minimize, maximize, close), titlebar, now_playing_bar, progressbar
                            (click/drag to seek), volume_slider, viewer + song_delegate (playlist
                            list), track_list_panel (per-track mute/solo rows), visualizer
                            (falling-note piano widget), toggle_switch (Audio/WWM mode, mute
                            rows), settings, key_configurator, key_catcher (captures a keypress
                            for rebinding), search_box, combo_box (palette-drawn chevron), glow (neon
                            glow + segmented LED bar painting helpers), toast,
                            animation, special (credits), dialog_style
src/utils/common.py        Colors enum + apply_skin()/apply_theme()/active_skin()/theme_bus
                            (live skin/theme switching, see "Skins & themes"), Singleton
                            metaclass, resource_path() helper, channel_color_hex()/
                            note_color_hex() (per-track visualizer color, from the active skin)
src/utils/skins.py         Pure skin registry: Skin/PianoColors dataclasses, SKINS (Default,
                            Cyberpunk), CHANNEL_COLORS (default note palette) (tested)
src/utils/midi_timing.py   Pure tempo-map / tick-to-seconds duration math, TickClock (incremental
                            per-track tick→seconds converter shared by note_events.py and
                            playback_stream.py) (tested)
src/utils/note_events.py   build_note_events() — precomputes all note on/off events per track for
                            the visualizer; summarize_tracks()/extract_track_names()/TrackSummary
                            for the mute/solo panel (tested)
src/utils/playback_stream.py  build_playback_messages() — track-tagged, time-sorted message
                            stream that drives live playback (see "How playback works") (tested)
src/utils/piano_layout.py  Pure 88-key keyboard geometry (white/black key positions) (tested)
src/utils/app_settings.py  Persisted settings (volume, Audio/WWM mode, playlist, selection, theme,
                            skin) as JSON, loaded on launch and saved on close (tested)
src/utils/playlist.py      Pure next-track index resolution for shuffle/repeat (tested)
src/utils/track_info.py    Track metadata extraction (artist/title from filename)
src/utils/window_geometry.py  Pure resize-edge hit-testing math for the frameless window (tested)
src/utils/wwm_macro.py     KeyManager (Singleton) — note→key mapping, keybinding persistence,
                            Windows PostMessage-based key injection into the game window (tested)
src/input/keybindings.json User's saved keybinding overrides (gitignored)
src/input/settings.json    User's saved app settings (gitignored)
src/input/logo.ico         App icon
TOH.sf2                    Bundled SoundFont (~420MB, tracked via Git LFS — see "Known rough edges")
app.spec                   PyInstaller build spec
installer.iss              Inno Setup installer script
build-installer.ps1        Drives PyInstaller + Inno Setup build
docs/screenshots/          README screenshots
tests/                     pytest suite for the pure-logic modules above
```

## How playback works (src/app.py)

- `Worker(QThread)` owns one MIDI file's playback. On start, it computes duration
  (`utils.midi_timing.calculate_duration`), precomputes `utils.note_events.build_note_events()`
  (emitted via `notes_ready`, feeds the visualizer) and `summarize_tracks()` (emitted via
  `tracks_ready`, feeds the mute/solo panel), then builds
  `utils.playback_stream.build_playback_messages()` — a single track-tagged, time-sorted list of
  every `note_on`/`note_off`/`control_change`/`program_change` message. The real-time loop
  iterates that list directly (not mido's own merged real-time iterator, which discards which
  track a message came from — track identity is required for per-track muting), using
  `time.perf_counter()` for timing.
- Note events within the same tick are batched into "chords" (`__flush_tick_events`) so
  simultaneous notes fire together rather than one at a time. `note_on` is filtered per-message
  against `Worker.__muted_tracks` (a `frozenset[int]`, swapped by reference from the GUI thread
  via `set_muted_tracks()` — same lock-free pattern as `__running`/`__paused`/`__volume`, no
  locks); `note_off` is always forwarded so an already-sounding note rings out to its own length
  instead of hanging if its track gets muted mid-note.
- In audio mode, notes go to `tinysoundfont.Synth`; in WWM mode, they go to
  `KeyManager.play_chord`, which maps each MIDI note (folded into a 48–83 playable range) to a
  keybinding and posts synthetic key events to the game window via `win32api`.
- Volume: the UI slider is a *master* multiplier, not a raw MIDI CC7 override —
  `Worker.__channel_base_volume` tracks each channel's own file-authored CC7 value (GM default
  100), and the slider scales that (`base * slider // 127`) so a track's own mix balance isn't
  clobbered. The shared `tinysoundfont.Synth` is constructed with `SYNTH_GAIN_DB = -6.0` headroom
  to avoid clipping on dense chords, and `max_voices=1024` on `sfload()` to avoid audible
  voice-stealing dropouts on tempo/note-dense files.
- Seeking (`Player.__on_seek_requested`, wired to `ProgressBar`'s click/drag) restarts `Worker`
  with `start_offset`; `run()` fast-forwards through the message stream up to that point (still
  applying program/control changes, muting audible output) before resuming normal real-time
  playback.
- Pause/resume adjusts `start_time` by the paused duration to keep sync correct.
- `Worker.elapsed_seconds()` is the single source of truth for playback position: both the
  visualizer (33ms poll) and the progress bar/time label (`PROGRESS_POLL_MS` poll in
  `Player.__update_progress`) read it, rather than counting timer ticks. It reports
  `start_offset` until `run()` has parsed the file and anchored its clock.
- `run()` wraps parsing and the playback loop in broad exception handlers, routing any failure to
  the existing error dialog (`Toast`) instead of the thread dying silently.
- `track_ended` is emitted only when a track finishes on its own (not when manually
  stopped/switched) and drives auto-advance; `Player.__next_index()` delegates to
  `utils.playlist.next_track_index()` so Next/auto-advance/repeat/shuffle all share one code path.

## Piano visualizer (src/ui/visualizer.py)

`PianoVisualizer` draws an 88-key keyboard with falling note bars, fed by `Worker.notes_ready` →
`Player.__on_notes_ready` → `PianoVisualizer.load_notes(events, duration)`, and repositioned each
frame via `set_position(seconds)` (polled from `Worker.elapsed_seconds()`). Notes are colored per
**originating MIDI track** (`utils.common.note_color_hex(track, is_drum)`), not per channel —
many real-world files route every instrument through the same channel and differentiate
instruments by track instead, so channel-based coloring would collapse everything into one color.
`set_muted_tracks(tracks)` hides a muted track's falling notes/keyboard highlights immediately.

## Per-track mute & solo (src/ui/track_list_panel.py)

`TrackListPanel` shows one row per track that produced at least one note (from
`Worker.tracks_ready`/`summarize_tracks()`), each with a color swatch matching the visualizer, a
mute `ToggleSwitch`, and a solo button. `Player.__on_track_toggled`/`__on_track_soloed` own the
actual `set[int]` of muted tracks, propagating it to the running `Worker` (if any) and the
visualizer on every change. Soloing a track mutes every other loaded track and remembers which
track is soloed (`Player.__soloed_track`); a manual mute change while soloed clears the solo
state rather than leaving a stale indicator. Mute/solo state resets when the user picks a
genuinely different song, but persists across a seek-triggered restart of the same song
(`Player.__reset_muted_tracks_if_song_changed` compares track indices, not just "did
`__start_playback` run").

## Skins & themes (src/utils/skins.py, src/utils/common.py)

A `Skin` bundles everything visual that varies: a full `Colors` palette per variant
(`"dark"`/`"light"`), the 16 note colors, piano key colors, corner radii (`radius_sm/md`), body/
heading/mono font families, and three effect flags that gate all skin-specific rendering (so the
Default skin, which sets none, renders exactly as it did before skins existed):

- `neon_glow` — soft outer glows: `ui.glow.draw_glow()` halos for painted shapes (visualizer:
  only *sounding* notes glow — haloing every falling bar blew the 33ms frame budget on dense
  files), `ui.glow.set_widget_glow()` (a `QGraphicsDropShadowEffect`, which can draw outside the
  widget's rect) for text, the play button, checked toggles, and status chips.
- `glass` — `window_background_qss()` (lit radial backdrop on the root, scoped by object name —
  a selector-less declaration would cascade and repaint the gradient per child) with transparent
  title/menu bars, `panel_background_qss()` sheen on cards, the visualizer drawn as a rounded card.
- `hud` — segmented LED progress/volume bars (`ui.glow.draw_segmented_bar()`; the volume slider
  then becomes handle-less click/drag-to-set), a scrolling telemetry grid + live readout chips
  (voices, notes/s, tracks, time) in the visualizer, PLAYING/STANDBY + AUDIO/WWM status chips in
  the Now Playing bar, and uppercase monospaced captions.

Category colors are `Colors` roles, not raw accents: `ACCENT_1` playback, `VOLUME` volume and
track on/off switches, `MODE` the Audio/WWM toggle, `SOLO`, `RED`, with `HIGHLIGHT` as the shared
gradient tail (`ToggleSwitch(accent=...)` picks a toggle's role). Skin (Settings → Skin) and Dark/Light preference
(Settings → Theme) are independent: `Skin.resolve_variant()` renders a dark-only skin (Cyberpunk)
dark while keeping the saved Light preference for when the user returns to a skin that has it;
the Theme toggle is disabled for single-variant skins.

`apply_skin()`/`apply_theme()` copy the active palette into the `Colors` members **in place**
(including `.qcolor`, via `setRgba`), set the app font, then emit `theme_bus.changed`. Every
widget restyles/repaints from its own `theme_bus.changed` handler, reading `Colors.X.value` and
`active_skin()` fresh — never cache a hex string or radius at construction time (caching the
shared `QColor` object is fine, since it's mutated in place). Unknown skin/theme names fall back
to defaults, so a bad settings file never crashes startup. QSS `font-family` takes one family, so
use `heading_font_qss()`/`mono_font_qss()` (which resolve a skin's fallback list against the
installed fonts, cached) rather than writing family names into QSS directly.

To add a skin: add an entry to `SKINS` in `utils/skins.py` with a palette defining **every**
`Colors` member (enforced by `tests/test_skins.py`). Adding a `Colors` member means adding it to
every skin's palettes. Panel QSS must use the widget's own class as selector (e.g. `Viewer {…}`),
not `QFrame {…}`, or the rule cascades into child `QLabel`s (which are `QFrame`s).

## Key mapping model (src/utils/wwm_macro.py)

Notes are described as scale degrees (`1`..`7`, plus sharps `#1/#4/#5` and flats `b3/b7`) across
three octave registers (`low`/`med`/`high`), matching the in-game instrument's 21-key layout
(QWERTY/ASDF/ZXCV rows). Default bindings mirror WWM's default Konghou keybinds. Users can remap
via Settings → Configure keybindings → `KeyConfigurator`, persisted to
`src/input/keybindings.json`. On load, `merge_keybindings()` overlays the saved file onto the
defaults, so a missing/corrupt/partial file falls back per-entry instead of crashing.

## Settings persistence (src/utils/app_settings.py)

`AppSettings` (volume, Audio/WWM mode, playlist file paths, last-selected index, theme, skin) is
loaded in
`Player.__load_saved_settings()` on launch and saved in `Player.__save_settings_to_disk()` on
close, as JSON at `src/input/settings.json` (same pattern as `keybindings.json`). Restoring the
last selection updates the header/highlights the row but deliberately does **not** mark it "now
playing" — nothing is actually playing yet at startup. Missing/corrupt settings files fall back
to defaults safely (never crash on a bad user file).

## Testing

`pytest` (config in `pyproject.toml`, `pythonpath = ["src"]`) covers the pure-logic modules only
— `utils/midi_timing.py`, `utils/note_events.py`, `utils/playback_stream.py`,
`utils/piano_layout.py`, `utils/app_settings.py`, `utils/playlist.py`, `utils/track_info.py`,
`utils/skins.py`, `utils/window_geometry.py`, `utils/wwm_macro.py` — since those don't touch Qt
in ways that need
mocking (filesystem-touching ones are isolated via `tmp_path`/`monkeypatch.chdir`). There is
deliberately no Qt-widget-level testing (no `pytest-qt`); GUI behavior is verified manually, or by
scripting the real `Player` class directly (constructing it, driving its private methods, and
calling `widget.grab()` to capture screenshots).

## Known rough edges

- `git log` messages in this repo are frequently uninformative (e.g. literally "Description:") —
  read the diffs directly if you need history context.
- `ruff` config in `pyproject.toml` is strict (docstrings required via `D`/pydocstyle Google
  convention, `PTH`, `ARG`, `COM`, etc.) — run `ruff check` before committing. Do **not** run
  `ruff format` broadly (see "Commands" above — pre-commit only enforces `ruff check --fix`, and
  the codebase's actual style disagrees with `ruff format`'s output).
  `tests/*` is exempted from docstring rules via `per-file-ignores`.
- Large binary artifacts live in the repo root: `TOH.sf2` (~420MB, Git LFS) and any built `.exe`
  (untracked build output) — be mindful of these when doing repo-wide operations; cloning/diffing
  is noticeably heavier than a typical Python repo because of this file.
