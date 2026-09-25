"""JS-callable backend for the web front end.

pywebview exposes every public method of Api to JavaScript as
`window.pywebview.api.<name>(...)` (returning a Promise). Api owns all player
state - playlist, selection, mode, volume, mute/solo, per-song transpose, song
details - but no UI: it drives the PlaybackEngine and pushes changes to the
page(s) through an injected `emit(event, payload)` callable. Everything
that needs the real window (dialogs, Explorer, the mini player) goes through
an injected Shell, so Api is testable without pywebview.

Threading: pywebview calls API methods on worker threads, global hotkeys call
them on the keyboard hook thread, and engine callbacks arrive on the playback
thread. Public methods serialize on one re-entrant lock. Engine callbacks and
the song-analysis worker never take it (the lock holder may be joining the
playback thread in __stop_engine, which would deadlock), so they only swap in
fresh objects and emit.
"""

import queue
import re
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import tinysoundfont

from utils.app_settings import SETTINGS_PATH, AppSettings, load_settings, save_settings
from utils.note_events import NoteEvent, TrackSummary
from utils.piano_layout import MIDI_NOTE_MAX, MIDI_NOTE_MIN, is_white_key, key_width, key_x_position
from utils.playback_engine import PlaybackCallbacks, PlaybackEngine, create_synth
from utils.playlist import (
    expand_midi_paths,
    index_after_move,
    index_after_removal,
    next_track_index,
    read_m3u,
    write_m3u,
)
from utils.resources import resource_path
from utils.skins import DEFAULT_SKIN, SKINS, VARIANTS
from utils.song_analysis import (
    MAX_TRANSPOSE,
    SongAnalysis,
    analyze_song,
    best_transpose,
    playable_fraction,
)
from utils.track_info import TrackInfo, parse_track_info
from utils.wwm_macro import NOTE_MAX, NOTE_MIN, KeyManager

Emit = Callable[[str, object], None]
SynthFactory = Callable[[Path], tinysoundfont.Synth]
# A key the game's keybinding UI accepts for a note: a single letter or digit.
BINDABLE_KEY: re.Pattern[str] = re.compile(r"^[A-Z0-9]$")


class Shell(Protocol):
    """What Api needs from the desktop around it (pywebview in the app, fakes in tests)."""

    def pick_midi_files(self) -> list[str]:
        """Show a multi-select "open MIDI files" dialog; empty if cancelled."""

    def pick_playlist_to_open(self) -> str|None:
        """Show an "open .m3u playlist" dialog; None if cancelled."""

    def pick_playlist_to_save(self) -> str|None:
        """Show a "save .m3u playlist" dialog; None if cancelled."""

    def reveal(self, path: str) -> None:
        """Show path selected in Explorer."""

    def toggle_mini_player(self) -> None:
        """Open the mini player if closed, else close it."""

    def mini_player_open(self) -> bool:
        """Return whether the mini player window is open."""

    def show_main_window(self) -> None:
        """Restore and raise the main window."""


class Api:
    """Player backend exposed to the web UI."""

    def __init__(self, emit: Emit, shell: Shell,
                       settings_path: Path=SETTINGS_PATH,
                       soundfont: Path|None=None,
                       synth_factory: SynthFactory=create_synth,
                       key_manager: Callable[[], KeyManager]=KeyManager) -> None:
        """Initialize the backend and restore saved settings.

        Args:
            emit: Pushes an (event name, JSON-serializable payload) to the page(s).
            shell: Dialogs, Explorer, and the mini player window.
            settings_path: Where settings are loaded from and saved to.
            soundfont: The SoundFont for Audio mode; defaults to the bundled one.
            synth_factory: Creates the shared synth on first Audio-mode play.
            key_manager: Returns the (singleton) WWM keybinding manager.
        """
        self.__emit: Emit = emit
        self.__shell: Shell = shell
        self.__settings_path: Path = settings_path
        self.__soundfont: Path = soundfont or resource_path("TOH.sf2")
        self.__synth_factory: SynthFactory = synth_factory
        self.__key_manager: Callable[[], KeyManager] = key_manager
        self.__synth: tinysoundfont.Synth|None = None
        self.__lock: threading.RLock = threading.RLock()
        self.__engine: PlaybackEngine|None = None
        self.__thread: threading.Thread|None = None
        self.__now_playing: int = -1
        self.__duration: float = 0.0
        self.__tracks: list[TrackSummary] = []
        self.__muted: set[int] = set()
        self.__soloed: int|None = None
        self.__shuffle: bool = False
        self.__repeat: bool = False
        # Song analyses by path (None = unreadable), filled by a background worker.
        self.__analyses: dict[str, SongAnalysis|None] = {}
        self.__analysis_queue: queue.Queue[str] = queue.Queue()
        self.__analysis_thread: threading.Thread|None = None
        settings: AppSettings = load_settings(settings_path)
        self.__volume: int = settings.volume
        self.__is_audio: bool = settings.is_audio_mode
        self.__skin: str = settings.skin if settings.skin in SKINS else DEFAULT_SKIN
        self.__theme: str = settings.theme if settings.theme in VARIANTS else "dark"
        self.__transpose: dict[str, int] = dict(settings.transpose)
        self.__files: list[str] = [f for f in settings.playlist if Path(f).exists()]
        self.__current: int = (settings.current_index
                               if 0 <= settings.current_index < len(self.__files)
                               else (0 if self.__files else -1))
        self.__queue_analysis(self.__files)

    # --- Queries -----------------------------------------------------------

    def get_state(self) -> dict:
        """Return everything the UI renders from, as one JSON-serializable snapshot.

        Returns:
            The full player state, including every skin's definition.
        """
        with self.__lock:
            return {
                "files": [self.__file_entry(path) for path in self.__files],
                "current": self.__current,
                "now_playing": self.__now_playing,
                "playing": self.__is_playing(),
                "paused": bool(self.__engine and self.__engine.paused),
                "duration": self.__duration,
                "volume": self.__volume,
                "is_audio": self.__is_audio,
                "shuffle": self.__shuffle,
                "repeat": self.__repeat,
                "skin": self.__skin,
                "theme": self.__theme,
                "skins": {name: asdict(skin) for name, skin in SKINS.items()},
                "tracks": [asdict(track) for track in self.__tracks],
                "muted": sorted(self.__muted),
                "soloed": self.__soloed,
                "wwm_range": [NOTE_MIN, NOTE_MAX],
                "max_transpose": MAX_TRANSPOSE,
                "mini_open": self.__shell.mini_player_open(),
            }

    def get_clock(self) -> dict:
        """Return the playback position for the UI to animate from.

        Once the playback thread has exited (error, or stopped at the end
        of the playlist) the position is 0 - an errored engine's clock would
        otherwise keep counting up from where it failed.

        Returns:
            {"position": seconds, "playing": whether the position is advancing}.
        """
        engine: PlaybackEngine|None = self.__engine
        if engine is None or not self.__is_playing():
            return {"position": 0.0, "playing": False}
        return {"position": engine.elapsed_seconds(), "playing": not engine.paused}

    @staticmethod
    def get_piano_layout() -> list[list]:
        """Return the 88-key geometry, normalized to a keyboard 1.0 wide.

        Computed by the (tested) utils.piano_layout math, so the canvas
        visualizer doesn't reimplement it.

        Returns:
            One [note, x, width, is_white] entry per key.
        """
        return [[note, key_x_position(note, 1.0), key_width(note, 1.0), is_white_key(note)]
                for note in range(MIDI_NOTE_MIN, MIDI_NOTE_MAX + 1)]

    # --- Playlist ----------------------------------------------------------

    def add_files(self) -> dict:
        """Ask the user for MIDI files and append them to the playlist.

        Returns:
            The updated state.
        """
        return self.add_paths(self.__shell.pick_midi_files() or [])

    def add_paths(self, paths: list[str]) -> dict:
        """Append MIDI files - expanding folders - to the playlist (e.g. from a drop).

        Args:
            paths: Files and/or folders; non-MIDI files are ignored.

        Returns:
            The updated state (also emitted, since drops don't come from JS).
        """
        found: list[str] = expand_midi_paths(list(paths))
        with self.__lock:
            self.__files.extend(found)
            if self.__current == -1 and self.__files:
                self.__current = 0
            self.__queue_analysis(found)
            state: dict = self.get_state()
        if found:
            self.__emit("state", state)
        return state

    def remove_file(self, index: int) -> dict:
        """Remove one song; stops playback if it's the one playing.

        Args:
            index: The playlist index to remove.

        Returns:
            The updated state.
        """
        with self.__lock:
            if not 0 <= index < len(self.__files):
                return self.get_state()
            if index == self.__now_playing:
                self.__stop_engine()
                self.__now_playing = -1
                self.__reset_song_state()
                self.__emit_clock()
            else:
                self.__now_playing = index_after_removal(self.__now_playing, index)
            del self.__files[index]
            if index == self.__current:
                self.__current = min(index, len(self.__files) - 1)
            else:
                self.__current = index_after_removal(self.__current, index)
            return self.get_state()

    def move_file(self, source: int, target: int) -> dict:
        """Reorder the playlist; selection and now-playing follow their songs.

        Args:
            source: The index of the song being moved.
            target: The index it should end up at.

        Returns:
            The updated state.
        """
        with self.__lock:
            count: int = len(self.__files)
            if not (0 <= source < count and 0 <= target < count) or source == target:
                return self.get_state()
            self.__files.insert(target, self.__files.pop(source))
            self.__current = index_after_move(self.__current, source, target)
            self.__now_playing = index_after_move(self.__now_playing, source, target)
            return self.get_state()

    def reveal_file(self, index: int) -> None:
        """Show a song's file in Explorer.

        Args:
            index: The playlist index to reveal.
        """
        with self.__lock:
            if 0 <= index < len(self.__files):
                self.__shell.reveal(self.__files[index])

    def clear_playlist(self) -> dict:
        """Stop playback and empty the playlist.

        Returns:
            The updated state.
        """
        with self.__lock:
            self.__stop_engine()
            self.__files.clear()
            self.__current = -1
            self.__now_playing = -1
            self.__reset_song_state()
            self.__emit_clock()
            return self.get_state()

    def save_playlist(self) -> bool:
        """Ask where to save, then write the playlist as .m3u.

        Returns:
            True if saved, False if cancelled.
        """
        path: str|None = self.__shell.pick_playlist_to_save()
        if not path:
            return False
        with self.__lock:
            write_m3u(Path(path), self.__files)
        return True

    def load_playlist(self) -> dict:
        """Ask for an .m3u playlist and replace the current playlist with it.

        Stops playback. Entries whose files no longer exist are skipped, with
        a status message saying how many.

        Returns:
            The updated state.
        """
        path: str|None = self.__shell.pick_playlist_to_open()
        if not path:
            return self.get_state()
        entries: list[str] = read_m3u(Path(path))
        files: list[str] = [entry for entry in entries if Path(entry).exists()]
        with self.__lock:
            self.__stop_engine()
            self.__files = files
            self.__current = 0 if files else -1
            self.__now_playing = -1
            self.__reset_song_state()
            self.__emit_clock()
            self.__queue_analysis(files)
            if len(files) < len(entries):
                self.__emit("status", {"message": f"Skipped {len(entries) - len(files)} "
                                                  "missing file(s) from the playlist."})
            return self.get_state()

    # --- Transport ---------------------------------------------------------

    def play_index(self, index: int) -> None:
        """Start playing the playlist entry at index from the beginning.

        Args:
            index: The playlist index to play.
        """
        with self.__lock:
            if not 0 <= index < len(self.__files):
                return
            self.__change_song(index)
            self.__start()

    def play_pause(self) -> None:
        """Pause/resume the running song, or start the selected one."""
        with self.__lock:
            if self.__is_playing():
                self.__engine.toggle_pause()
                self.__emit_clock()
                self.__emit("state", self.get_state())
            elif self.__files:
                self.__start()

    def next_track(self) -> None:
        """Advance to the next song, honoring shuffle/repeat."""
        with self.__lock:
            index: int|None = next_track_index(self.__current, len(self.__files),
                                               shuffle=self.__shuffle, repeat=self.__repeat)
            if index is not None:
                self.__change_song(index)
                self.__start()

    def previous_track(self) -> None:
        """Go back to the previous song, if any."""
        with self.__lock:
            if self.__files and self.__current > 0:
                self.__change_song(self.__current - 1)
                self.__start()

    def seek(self, seconds: float) -> None:
        """Restart the selected song at the given position, keeping mute/solo state.

        Args:
            seconds: The position to seek to.
        """
        with self.__lock:
            if self.__files and self.__current != -1:
                self.__start(start_offset=max(0.0, float(seconds)))

    # --- Transpose ---------------------------------------------------------

    def set_transpose(self, semitones: int) -> dict:
        """Set the now-playing (else selected) song's transpose, remembered per song.

        If that song is playing, it restarts at the same position (keeping a
        pause) so the change is heard immediately.

        Args:
            semitones: The shift, clamped to +/-MAX_TRANSPOSE.

        Returns:
            The updated state.
        """
        with self.__lock:
            index: int = self.__now_playing if self.__now_playing >= 0 else self.__current
            if not 0 <= index < len(self.__files):
                return self.get_state()
            path: str = self.__files[index]
            shift: int = max(-MAX_TRANSPOSE, min(MAX_TRANSPOSE, int(semitones)))
            if shift:
                self.__transpose[path] = shift
            else:
                self.__transpose.pop(path, None)
            if index == self.__now_playing and self.__is_playing():
                was_paused: bool = self.__engine.paused
                self.__start(start_offset=self.__engine.elapsed_seconds())
                if was_paused:
                    self.__engine.toggle_pause()
                    self.__emit_clock()
            self.__emit("details", self.__file_entry(path))
            return self.get_state()

    def auto_transpose(self) -> dict:
        """Transpose the now-playing (else selected) song to fit WWM's range best.

        Returns:
            The updated state.
        """
        with self.__lock:
            index: int = self.__now_playing if self.__now_playing >= 0 else self.__current
            if not 0 <= index < len(self.__files):
                return self.get_state()
            analysis: SongAnalysis|None = self.__analysis(self.__files[index])
            if analysis is None:
                return self.get_state()
            return self.set_transpose(best_transpose(analysis.pitches))

    # --- Settings ----------------------------------------------------------

    def set_volume(self, volume: int) -> None:
        """Set the master volume, live.

        Args:
            volume: The new master volume, in the MIDI CC7 range (0-127).
        """
        with self.__lock:
            self.__volume = max(0, min(127, int(volume)))
            if self.__engine:
                self.__engine.set_volume(self.__volume)

    def set_audio_mode(self, is_audio: bool) -> None:
        """Choose Audio (True) or WWM (False) mode; applies from the next play.

        Args:
            is_audio: True for Audio mode, False for WWM mode.
        """
        with self.__lock:
            self.__is_audio = bool(is_audio)
            self.__emit("state", self.get_state())

    def set_shuffle(self, enabled: bool) -> None:
        """Toggle shuffle.

        Args:
            enabled: Whether shuffle is on.
        """
        with self.__lock:
            self.__shuffle = bool(enabled)

    def set_repeat(self, enabled: bool) -> None:
        """Toggle repeat-playlist.

        Args:
            enabled: Whether repeat is on.
        """
        with self.__lock:
            self.__repeat = bool(enabled)

    def set_skin(self, name: str) -> None:
        """Switch skin; unknown names fall back to the default.

        Args:
            name: A key of utils.skins.SKINS.
        """
        with self.__lock:
            self.__skin = name if name in SKINS else DEFAULT_SKIN
            self.__emit("state", self.get_state())

    def set_theme(self, name: str) -> None:
        """Set the Dark/Light preference; unknown names fall back to dark.

        Args:
            name: "dark" or "light".
        """
        with self.__lock:
            self.__theme = name if name in VARIANTS else "dark"
            self.__emit("state", self.get_state())

    def toggle_mini_player(self) -> dict:
        """Open or close the always-on-top mini player window.

        Returns:
            The updated state.
        """
        self.__shell.toggle_mini_player()
        state: dict = self.get_state()
        self.__emit("state", state)
        return state

    def show_main_window(self) -> None:
        """Close the mini player (if open) and bring the main window back."""
        if self.__shell.mini_player_open():
            self.__shell.toggle_mini_player()
        self.__shell.show_main_window()
        self.__emit("state", self.get_state())

    # --- Keybindings -------------------------------------------------------

    def get_keybindings(self) -> dict:
        """Return the WWM key bindings for the editor.

        Returns:
            {"bindings": {octave: {degree: key}}, "defaults": same shape}.
        """
        manager: KeyManager = self.__key_manager()
        return {"bindings": manager.bindings, "defaults": manager.default_bindings}

    def set_keybinding(self, octave: str, degree: str, key: str) -> dict:
        """Rebind one natural scale degree (letters/digits only, no duplicates).

        Sharps/flats aren't edited directly: KeyManager keeps them as
        modifier+key of their natural degree's key.

        Args:
            octave: "low", "med", or "high".
            degree: A natural scale degree, "1".."7".
            key: A single letter or digit.

        Returns:
            {"ok": bool, "error": message or "", "bindings": current bindings}.
        """
        manager: KeyManager = self.__key_manager()
        key = str(key).upper()
        error: str = ""
        if not BINDABLE_KEY.match(key):
            error = "Allowed keys are A-Z and 0-9."
        elif degree not in manager.bindings.get(octave, {}) or not degree.isdigit():
            error = "Only natural notes (1-7) can be rebound."
        else:
            taken: dict[str, str] = {
                bound: f"{name.title()} {note}"
                for name, notes in manager.bindings.items()
                for note, bound in notes.items()
                if note.isdigit() and (name, note) != (octave, degree)}
            if key in taken:
                error = f"{key} is already used by {taken[key]}."
        if not error:
            manager.update_keybinding(octave, degree, key)
        return {"ok": not error, "error": error, "bindings": manager.bindings}

    def reset_keybindings(self) -> dict:
        """Restore the default WWM key bindings.

        Returns:
            The (default) bindings.
        """
        manager: KeyManager = self.__key_manager()
        manager.reset_keybindings()
        return {"bindings": manager.bindings, "defaults": manager.default_bindings}

    # --- Mute / solo -------------------------------------------------------

    def set_track_enabled(self, track: int, enabled: bool) -> dict:
        """Mute or unmute one track, live; a manual change drops any solo.

        Args:
            track: The MIDI track index.
            enabled: True for audible, False for muted.

        Returns:
            {"muted": [...], "soloed": index or None}.
        """
        with self.__lock:
            self.__soloed = None
            if enabled:
                self.__muted.discard(track)
            else:
                self.__muted.add(track)
            return self.__apply_mute()

    def solo_track(self, track: int, soloed: bool) -> dict:
        """Solo one track (mute every other loaded track), or un-solo to make all audible.

        Args:
            track: The MIDI track index.
            soloed: True to solo track, False to restore every track.

        Returns:
            {"muted": [...], "soloed": index or None}.
        """
        with self.__lock:
            loaded: set[int] = {summary.index for summary in self.__tracks}
            self.__soloed = track if soloed else None
            self.__muted = (loaded - {track}) if soloed else set()
            return self.__apply_mute()

    # --- Lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Persist settings and stop playback and audio; call on window close."""
        with self.__lock:
            save_settings(AppSettings(
                volume=self.__volume,
                is_audio_mode=self.__is_audio,
                playlist=list(self.__files),
                current_index=self.__current,
                theme=self.__theme,
                skin=self.__skin,
                transpose=dict(self.__transpose),
            ), self.__settings_path)
            self.__stop_engine()
            if self.__synth is not None:
                self.__synth.stop()
                self.__synth = None

    # --- Internals ---------------------------------------------------------

    def __file_entry(self, path: str) -> dict:
        """Return a playlist entry's display data, including any finished analysis.

        Args:
            path: The MIDI file path.

        Returns:
            {"path", "title", "artist", "transpose", "duration", "tracks",
            "in_range"}; the last three are None until analyzed (or if the
            file couldn't be read).
        """
        info: TrackInfo = parse_track_info(Path(path).name)
        shift: int = self.__transpose.get(path, 0)
        analysis: SongAnalysis|None = self.__analyses.get(path)
        return {
            "path": path, "title": info.title, "artist": info.artist, "transpose": shift,
            "duration": analysis.duration if analysis else None,
            "tracks": analysis.track_count if analysis else None,
            "in_range": playable_fraction(analysis.pitches, shift) if analysis else None,
        }

    def __queue_analysis(self, paths: list[str]) -> None:
        """Queue songs for background analysis, starting the worker on first use.

        Args:
            paths: The MIDI files to analyze (already-analyzed ones are skipped).
        """
        for path in paths:
            if path not in self.__analyses:
                self.__analysis_queue.put(path)
        if self.__analysis_thread is None:
            self.__analysis_thread = threading.Thread(
                target=self.__analyze_forever, name="song-analysis", daemon=True)
            self.__analysis_thread.start()

    def __analyze_forever(self) -> None:
        """Analyze queued songs one by one, pushing each result to the page."""
        while True:
            path: str = self.__analysis_queue.get()
            if path in self.__analyses:
                continue
            self.__analysis(path)
            self.__emit("details", self.__file_entry(path))

    def __analysis(self, path: str) -> SongAnalysis|None:
        """Return a song's cached analysis, computing it now if needed.

        Args:
            path: The MIDI file.

        Returns:
            The analysis, or None if the file couldn't be read.
        """
        if path not in self.__analyses:
            try:
                self.__analyses[path] = analyze_song(path)
            except Exception:  # noqa: BLE001 - any unreadable file just has no details
                self.__analyses[path] = None
        return self.__analyses[path]

    def __is_playing(self) -> bool:
        """Return whether a playback thread is alive (playing or paused).

        Returns:
            True while a song is loaded in the engine.
        """
        return self.__thread is not None and self.__thread.is_alive()

    def __change_song(self, index: int) -> None:
        """Select index; clears mute/solo only when it's actually a different song.

        Args:
            index: The playlist index being switched to.
        """
        if index != self.__current:
            self.__muted.clear()
            self.__soloed = None
        self.__current = index

    def __reset_song_state(self) -> None:
        """Forget the loaded song's duration, tracks, and mute/solo state."""
        self.__duration = 0.0
        self.__tracks = []
        self.__muted.clear()
        self.__soloed = None

    def __stop_engine(self) -> None:
        """Stop the running engine (if any) and wait for its thread to finish."""
        if self.__engine is not None:
            self.__engine.stop()
        if self.__thread is not None and self.__thread is not threading.current_thread():
            self.__thread.join()
        self.__engine = None
        self.__thread = None

    def __start(self, start_offset: float=0.0) -> None:
        """(Re)start playback of the selected song at start_offset.

        Args:
            start_offset: Seconds into the song to start from.
        """
        self.__stop_engine()
        synth: tinysoundfont.Synth|None = None
        if self.__is_audio:
            if self.__synth is None:
                self.__emit("status", {"message": "Loading SoundFont..."})
                self.__synth = self.__synth_factory(self.__soundfont)
            synth = self.__synth
        path: str = self.__files[self.__current]
        engine: PlaybackEngine = PlaybackEngine(
            path, synth, self.__is_audio, start_offset, frozenset(self.__muted),
            self.__callbacks_for(start_offset), transpose=self.__transpose.get(path, 0))
        engine.set_volume(self.__volume)
        self.__engine = engine
        self.__now_playing = self.__current
        self.__thread = threading.Thread(target=engine.run, name="playback", daemon=True)
        self.__thread.start()
        self.__emit("state", self.get_state())

    def __callbacks_for(self, start_offset: float) -> PlaybackCallbacks:
        """Build the engine callbacks that forward progress to the page.

        Args:
            start_offset: The position this engine starts at (for the clock event).

        Returns:
            The callbacks for a new engine.
        """
        def on_duration(seconds: float) -> None:
            self.__duration = seconds
            self.__emit("duration", {"seconds": seconds})
            self.__emit("clock", {"position": start_offset, "playing": True})

        def on_notes(events: list[NoteEvent]) -> None:
            self.__emit("notes", {"notes": [[e.start, e.end, e.note, e.track, e.is_drum]
                                            for e in events]})

        def on_tracks(tracks: list[TrackSummary]) -> None:
            self.__tracks = tracks
            self.__emit("tracks", {"tracks": [asdict(track) for track in tracks],
                                   "muted": sorted(self.__muted), "soloed": self.__soloed})

        def on_error(message: str) -> None:
            self.__now_playing = -1
            self.__emit("error", {"message": message})
            self.__emit("clock", {"position": 0.0, "playing": False})

        def on_ended() -> None:
            # Auto-advance on a fresh thread: next_track() stops/joins the
            # current playback thread, which is the one running this callback.
            threading.Thread(target=self.__advance_after_end, daemon=True).start()

        return PlaybackCallbacks(on_duration=on_duration, on_notes=on_notes,
                                 on_tracks=on_tracks, on_error=on_error, on_ended=on_ended)

    def __advance_after_end(self) -> None:
        """Advance after a song ends on its own, or go idle at the playlist's end."""
        with self.__lock:
            index: int|None = next_track_index(self.__current, len(self.__files),
                                               shuffle=self.__shuffle, repeat=self.__repeat)
            if index is None:
                self.__stop_engine()
                self.__now_playing = -1
                self.__emit_clock()
                self.__emit("state", self.get_state())
                return
            self.__change_song(index)
            self.__start()

    def __apply_mute(self) -> dict:
        """Push the mute set to the running engine and return it for the UI.

        Returns:
            {"muted": [...], "soloed": index or None}.
        """
        if self.__engine is not None:
            self.__engine.set_muted_tracks(frozenset(self.__muted))
        return {"muted": sorted(self.__muted), "soloed": self.__soloed}

    def __emit_clock(self) -> None:
        """Push the current clock to the page."""
        self.__emit("clock", self.get_clock())
