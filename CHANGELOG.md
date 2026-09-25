# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- **Skins**: pick the app's look in Settings → Skin; it applies live and is remembered between
  launches. Ships with **Default** and **Cyberpunk**: a dark glass, sci-fi HUD look with
  rounded cards, a glowing neon accent per category (blue playback, green volume, purple mode,
  yellow solo, red alerts), segmented LED progress/volume bars, a telemetry grid and live
  readouts (voices, notes/s, tracks, time) in the visualizer, playback/mode status chips, and
  monospaced instrument-style numbers.
- **Light theme**: a Dark/Light toggle in Settings that restyles the whole app live, and is
  remembered between launches. (Dark-only skins like Cyberpunk keep your choice for when you
  switch back.)
- An empty-state message in the playlist when no songs are loaded.
- A clear button in the song search box.
- Scrollbars styled to match the active theme.

### Fixed

- The elapsed-time label and progress bar slowly drifting out of sync with actual playback
  (and with the visualizer) on longer songs.
- A corrupt or incomplete `keybindings.json` breaking WWM mode; missing or invalid entries now
  fall back to the default keybinds.
- The `wwm-player` console command failing to start the app.

## [2.0.0] - 2026-08-22

### Added

- **Falling-note piano visualizer**: an 88-key keyboard with notes falling toward it in sync
  with playback, colored per instrument track rather than MIDI channel.
- **Per-track mute & solo**: a Tracks panel lists every instrument in the loaded file with a
  color swatch, mute toggle, and solo button, live in both Audio and WWM mode.
- **Seek**: click or drag anywhere on the progress bar to jump to that point in the track.
- **Settings persistence**: volume, Audio/WWM mode, and your playlist/selection are restored
  the next time you launch the app.
- **Auto-forward, shuffle, and repeat** playback for the playlist.
- Toast-style error/status notifications (e.g. when WWM mode can't find the game window).
- A custom frameless window with its own title bar (minimize/maximize/close) and an animated,
  click/drag-seekable progress bar.
- `README.md` screenshots, plus rewritten `CONTRIBUTING.md`, `SECURITY.md`, and
  `CODE_OF_CONDUCT.md`.

### Changed

- Bundled SoundFont switched to `TOH.sf2` (Timbres of Heaven), tracked via Git LFS.
- Volume control now acts as a master multiplier over each track's own MIDI volume (CC7)
  instead of overriding it outright, so a track's own mix balance is preserved.
- Synth headroom/voice limits tuned (`gain`, `max_voices`) to avoid clipping and voice-stealing
  dropouts on dense or tempo-heavy files.
- Full UI restyle: shuffle/repeat buttons, key remapping dialog, and settings dialog all
  reworked to match the app's dark theme.
- Local development setup now uses [uv](https://docs.astral.sh/uv/) instead of plain
  `pip`/`venv`.

### Fixed

- App freezing during playback.
- Notes losing sync/dropping during playback of dense files.
- Notes being shifted to the wrong octave.
- Error toast notifications sometimes staying visible on screen after being dismissed.
- Installer's post-install "Launch app" step failing with *"CreateProcess failed; code 740"*
  on the app's elevation-required executable.

[2.0.0]: https://github.com/KrapFey/wwm-midi-player/compare/v1.5...v2.0.0
