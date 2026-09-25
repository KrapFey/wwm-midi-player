"""Simple PySide6 MIDI player."""

import contextlib
import sys
import time
from pathlib import Path
from typing import override

import keyboard
import mido
import tinysoundfont
import win32gui
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QResizeEvent,
    Qt,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ui.buttons.play import PlayButton
from ui.now_playing_bar import NowPlayingBar
from ui.search_box import SearchBox
from ui.settings import SettingsDialog
from ui.song_delegate import ARTIST_ROLE, TITLE_ROLE
from ui.special import SpecialDialog
from ui.titlebar import TitleBar
from ui.toast import Toast
from ui.track_list_panel import TrackListPanel
from ui.viewer import Viewer
from ui.visualizer import PianoVisualizer
from utils.app_settings import AppSettings, load_settings, save_settings
from utils.common import (
    RADIUS_SM,
    RESIZE_MARGIN,
    SPACING_MD,
    SPACING_XS,
    Colors,
    apply_theme,
    current_theme,
    resource_path,
    theme_bus,
)
from utils.midi_timing import calculate_duration
from utils.note_events import (
    DRUM_CHANNEL,
    NoteEvent,
    TrackSummary,
    build_note_events,
    summarize_tracks,
)
from utils.playback_stream import PlaybackMessage, build_playback_messages
from utils.playlist import next_track_index
from utils.track_info import TrackInfo, parse_track_info
from utils.window_geometry import compute_resize_edges
from utils.wwm_macro import KeyManager

# Headroom (relative dB) applied to the shared synth's output so dense
# chords/many simultaneous channels at high volume don't sum past 0dBFS.
SYNTH_GAIN_DB: float = -6.0
# How often the progress bar re-reads the worker's playback position.
PROGRESS_POLL_MS: int = 250


class Worker(QThread):
    """MIDI player worker."""

    duration_ready: Signal = Signal(float)
    error: Signal = Signal(str)
    track_ended: Signal = Signal()
    notes_ready: Signal = Signal(list)
    tracks_ready: Signal = Signal(list)

    def __init__(self, filename: str, synth: tinysoundfont.Synth|None,
                      is_audio: bool=False, start_offset: float=0.0,
                      muted_tracks: frozenset[int]=frozenset()) -> None:
        """Initialize worker.

        synth is a shared, already-started, already-soundfont-loaded Synth
        owned by Player and reused across tracks (required when is_audio);
        Worker never loads a SoundFont or tears the synth down itself, since
        reloading the ~420MB .sf2 on every track change is the expensive part.

        start_offset seeks to that many seconds into the song: run() fast-
        forwards through messages up to that point (still applying
        program/control changes so instrument state is correct) without
        actually sounding notes or sleeping, then resumes normal playback.

        muted_tracks is the initial set of MIDI track indices to silence;
        set_muted_tracks() updates it live while this Worker is running.

        Args:
            filename: Path to the MIDI file to play.
            synth: Shared audio synth to play through, or None in WWM mode.
            is_audio: True for Audio mode (synth), False for WWM mode
                (simulated keypresses).
            start_offset: Seconds into the song to seek to before playing.
            muted_tracks: MIDI track indices to silence from the start.
        """
        super().__init__()
        self.__is_audio: bool = is_audio
        self.__filename: str = filename
        self.__synth: tinysoundfont.Synth|None = synth
        self.__key_manager: KeyManager = KeyManager()
        self.__running: bool = True
        self.__paused: bool = False
        self.__volume: int = 100
        self.__sent_volume: int|None = None
        # GM default channel volume is 100; tracks commonly send their own
        # CC7 to set a per-channel mix balance, which __volume must scale
        # rather than overwrite (see __send_channel_volume).
        self.__channel_base_volume: list[int] = [100] * 16
        self.__muted_tracks: frozenset[int] = muted_tracks
        self.__start_time: float = 0.0
        # False until run() has parsed the file and anchored __start_time;
        # until then elapsed_seconds() reports start_offset instead of
        # perf_counter() minus an unset (0.0) start time.
        self.__clock_started: bool = False
        self.__last_song_time: float = start_offset
        self.__start_offset: float = start_offset

    @property
    def paused(self) -> bool:
        """Return pause state.

        Returns:
            True if playback is currently paused.
        """
        return self.__paused

    def set_muted_tracks(self, tracks: frozenset[int]) -> None:
        """Live-update muted tracks; takes effect on the next tick flush.

        Swap-by-reference, not in-place mutation - matches __running/
        __paused/__volume/__channel_base_volume's existing lock-free pattern
        in this class. Player always hands in a fresh frozenset, so a read
        here mid-swap always sees one fully-formed set or the other.

        Args:
            tracks: The MIDI track indices that should now be muted.
        """
        self.__muted_tracks = tracks

    def elapsed_seconds(self) -> float:
        """Return seconds elapsed in the current song, frozen while paused.

        Safe to call from the GUI thread while the worker thread runs: mirrors
        the same perf_counter()-minus-start_time math run() uses internally to
        drive its own wait loop, reading the same instance attributes run()
        maintains (float reads/writes are atomic under the GIL, matching the
        existing lock-free precedent for __paused/__running in this class).

        Returns:
            The current playback position in seconds.
        """
        if self.__paused or not self.__clock_started:
            return self.__last_song_time
        return time.perf_counter() - self.__start_time

    def __calculate_duration(self, midi: mido.MidiFile) -> None:
        """Calculate overall duration.

        Args:
            midi: The parsed MIDI file to measure.
        """
        self.duration_ready.emit(calculate_duration(midi))

    def __add_note(self, synth: tinysoundfont.Synth|None, track: int, msg: mido.Message,
                         chord_notes: list[tuple[int, int, int]]) -> None:
        """Add a chord note, or apply a note_off.

        Only note_on is filtered by the current mute set - a note_off is
        always forwarded even if its track has since been muted, so an
        already-sounding note (audio mode) finishes at its own
        written-in-file length instead of hanging until the next
        stop/pause/all-notes-off. WWM has no sustain concept (each note_on
        is one discrete keydown+keyup pulse via play_chord), so muting there
        is inherently immediate.

        Args:
            synth: The shared audio synth, or None in WWM mode.
            track: The MIDI track index msg originated from.
            msg: The note_on/note_off message to process.
            chord_notes: The current tick's accumulated (channel, note,
                velocity) tuples; appended to in place for a passing note_on.
        """
        if msg.type == "note_on" and msg.velocity > 0:
            if track not in self.__muted_tracks:
                chord_notes.append((msg.channel, msg.note, msg.velocity))
        elif msg.type == "note_off" and self.__is_audio:
            synth.noteoff(msg.channel, msg.note)

    def __flush_tick_events(self, handle: int, synth: tinysoundfont.Synth|None,
                                  tick_events: list[tuple[int, mido.Message]],
                                  mute: bool=False) -> None:
        """Flush tick events.

        mute discards the batch without sounding anything - used while fast-
        forwarding through a seek, so skipped notes aren't heard/pressed all
        at once.

        Args:
            handle: The target window handle for WWM mode key injection.
            synth: The shared audio synth, or None in WWM mode.
            tick_events: The (track, message) pairs accumulated for the tick
                that just elapsed; cleared in place once flushed.
            mute: If True, discard the batch instead of sounding it.
        """
        if not tick_events:
            return
        if mute:
            tick_events.clear()
            return
        chord_notes: list[tuple[int, int, int]] = []
        for track, msg in tick_events:
            self.__add_note(synth, track, msg, chord_notes)
        if chord_notes:
            if self.__is_audio:
                for channel, n, velocity in chord_notes:
                    synth.noteon(channel, n, velocity)
            else:
                self.__key_manager.play_chord(handle, [n for _, n, _ in chord_notes])
        tick_events.clear()

    def __send_channel_volume(self, synth: tinysoundfont.Synth, channel: int) -> None:
        """Send channel's combined (file base x our master slider) volume.

        Args:
            synth: The shared audio synth.
            channel: The MIDI channel to update.
        """
        combined: int = (self.__channel_base_volume[channel] * self.__volume) // 127
        synth.control_change(channel, 7, combined)

    def __apply_volume(self, synth: tinysoundfont.Synth|None) -> None:
        """Re-send every channel's combined volume when the master slider has changed.

        Args:
            synth: The shared audio synth, or None in WWM mode (no-op).
        """
        if synth is not None and self.__volume != self.__sent_volume:
            for channel in range(16):
                self.__send_channel_volume(synth, channel)
            self.__sent_volume = self.__volume

    def __wait_until(self, start_time: float, target_song_time: float) -> None:
        """Sleep until target_song_time has elapsed since start_time.

        Sleeps in one coarse chunk down to a small margin, then finishes with
        short 1ms sleeps for accurate timing, instead of spin-sleeping in 1ms
        steps for the entire wait (which wastes CPU on long rests and is
        finer-grained than the OS timer can honor anyway).

        Args:
            start_time: The perf_counter() timestamp playback started from.
            target_song_time: The song-time offset (seconds) to wait until.
        """
        fine_margin: float = 0.005
        while self.__running:
            remaining: float = target_song_time - (time.perf_counter() - start_time)
            if remaining <= 0:
                return
            time.sleep(remaining - fine_margin if remaining > fine_margin else 0.001)

    @override
    def run(self) -> None:
        """Worker body with proper chord grouping and tempo handling."""
        try:
            player: mido.MidiFile = mido.MidiFile(self.__filename)
        except mido.midifiles.meta.KeySignatureError:
            self.error.emit("Invalid MIDI File.\nPlease select valid MIDI file.")
            return
        except Exception as exc:  # noqa: BLE001 - surface any parse failure to the UI
            self.error.emit(f"Failed to load MIDI file.\n{exc}")
            return
        synth: tinysoundfont.Synth|None = self.__synth
        handle: int = 0
        if not self.__is_audio:
            handle = win32gui.FindWindow(None, "Where Winds Meet")
            if not handle:
                self.error.emit("Where Winds Meet is not running.\n"
                                "Please run the game then try again.")
                return
        elif synth is not None:
            # GM channel 10 (0-indexed 9) defaults to a drum kit even when the
            # file never sends an explicit program_change for it.
            synth.program_change(DRUM_CHANNEL, 0, is_drums=True)
        tick_events: list[tuple[int, mido.Message]] = []
        natural_end: bool = True
        try:
            self.__calculate_duration(player)
            events: list[NoteEvent] = build_note_events(player)
            self.notes_ready.emit(events)
            self.tracks_ready.emit(summarize_tracks(player, events))
            messages: list[PlaybackMessage] = build_playback_messages(player)
            current_song_time: float = .0
            skipping: bool = self.__start_offset > 0.0
            # Offset by start_offset so elapsed_seconds() already reads the
            # seek target while fast-forwarding, instead of briefly reading 0.
            self.__start_time = time.perf_counter() - self.__start_offset
            self.__clock_started = True
            for pm in messages:
                if not self.__running:
                    natural_end = False
                    break
                if self.__paused:
                    self.__last_song_time = current_song_time
                    if self.__is_audio and synth is not None:
                        for channel in range(16):
                            synth.control_change(channel, 123, 0)
                    pause_start: float = time.perf_counter()
                    while self.__paused and self.__running:
                        time.sleep(0.05)
                    self.__start_time += (time.perf_counter() - pause_start)
                if pm.time > current_song_time:
                    # All messages accumulated so far share the tick that has
                    # already elapsed - flush them as one chord before waiting
                    # for the next tick.
                    self.__flush_tick_events(handle, synth, tick_events, mute=skipping)
                    current_song_time = pm.time
                    if skipping and current_song_time >= self.__start_offset:
                        # Fast-forward is done: re-anchor the clock so
                        # __wait_until treats current_song_time as "now"
                        # instead of trying to catch up instantly.
                        skipping = False
                        self.__start_time = time.perf_counter() - current_song_time
                    if not skipping:
                        self.__wait_until(self.__start_time, current_song_time)
                msg: mido.Message = pm.message
                if msg.type in ("note_on", "note_off"):
                    tick_events.append((pm.track, msg))
                elif msg.type == "control_change" and self.__is_audio and synth is not None:
                    if msg.control == 7:
                        # Track the file's own per-channel mix balance
                        # instead of forwarding it as-is, which would
                        # silently override our master volume slider for
                        # any channel the file sets volume on.
                        self.__channel_base_volume[msg.channel] = msg.value
                        self.__send_channel_volume(synth, msg.channel)
                    else:
                        synth.control_change(msg.channel, msg.control, msg.value)
                elif msg.type == "program_change" and self.__is_audio and synth is not None:
                    synth.program_change(msg.channel, msg.program,
                                          is_drums=msg.channel == DRUM_CHANNEL)
                if self.__is_audio:
                    self.__apply_volume(synth)
            self.__flush_tick_events(handle, synth, tick_events, mute=skipping)
        except Exception as exc:  # noqa: BLE001 - surface any playback failure to the UI
            natural_end = False
            self.error.emit(f"Playback error.\n{exc}")
        finally:
            # Silence any lingering notes without tearing down the shared,
            # already-loaded synth - it's reused by the next track.
            if self.__is_audio and synth is not None:
                for channel in range(16):
                    synth.control_change(channel, 123, 0)
        if natural_end:
            self.track_ended.emit()

    def stop(self) -> None:
        """Stop worker."""
        self.__running = False

    def toggle_pause(self) -> None:
        """Pause worker."""
        self.__paused = not self.__paused

    def set_volume(self, volume: int) -> None:
        """Set synth volume.

        Args:
            volume: The new master volume, in the MIDI CC7 range (0-127).
        """
        self.__volume = volume

class Player(QMainWindow):
    """MIDI Player."""

    hotkey_triggered: Signal = Signal(str)

    def __init__(self) -> None:
        """Initialize MIDI Player."""
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setMouseTracking(True)
        screen_size: QRect = QGuiApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(QSize(screen_size.width() // 2, screen_size.height() // 2))
        self.__resize_edges: Qt.Edge = Qt.Edge(0)
        self.__files: list[str] = []
        self.__current_index: int = -1
        self.__thread: Worker|None = None
        self.__repeat: bool = False
        self.__shuffle: bool = False
        self.__toast: Toast|None = None
        self.__soundfont: Path = resource_path("TOH.sf2")
        self.__synth: tinysoundfont.Synth|None = None
        self.__current: int = -1
        self.__duration: int = 0
        self.__search: QLineEdit
        self.__songs: Viewer
        self.__now_playing_bar: NowPlayingBar
        self.__repeat_action: QAction
        self.__shuffle_action: QAction
        self.__root: QWidget
        self.__central_layout: QVBoxLayout
        self.__content_widget: QWidget
        self.__title_bar: TitleBar
        self.__menu_bar: QMenuBar
        self.__progress_timer: QTimer
        self.__visualizer: PianoVisualizer
        self.__visualizer_timer: QTimer
        self.__muted_tracks: set[int] = set()
        self.__soloed_track: int|None = None
        self.__loaded_track_indices: set[int] = set()
        self.__track_list_panel: TrackListPanel
        self.__stacked_playlist: QStackedLayout
        self.__playlist_tab_group: QButtonGroup
        self.__construct_menu_bar()
        self.__construct_layout()
        self.__wire_now_playing_bar()
        self.__bind_shortcuts()
        theme_bus.changed.connect(self.__on_theme_changed)
        self.__load_saved_settings()

    @Slot()
    def __on_theme_changed(self) -> None:
        """Re-apply the QSS this class owns directly after a theme switch.

        Every child widget restyles itself independently via its own
        `theme_bus.changed` connection - this only covers the menu bar,
        Songs/Tracks tab buttons, and root/content backgrounds, which
        `Player` builds and styles inline.
        """
        self.__style_menu_bar()
        self.__style_tab_buttons()
        self.__style_root()

    def __bind_shortcuts(self) -> None:
        """Bind shortcuts.

        keyboard.add_hotkey() callbacks run on the keyboard library's own hook
        thread, not the Qt GUI thread - calling widget methods directly from
        there is undefined behavior (occasional hangs/freezes). Route every
        hotkey through a Qt signal instead: emitting is thread-safe, and Qt
        auto-queues delivery onto the GUI thread since emitter and receiver
        threads differ.
        """
        self.hotkey_triggered.connect(self.__on_hotkey)
        keyboard.add_hotkey("f9", lambda: self.hotkey_triggered.emit("previous"))
        keyboard.add_hotkey("f10", lambda: self.hotkey_triggered.emit("play"))
        keyboard.add_hotkey("f11", lambda: self.hotkey_triggered.emit("next"))
        keyboard.add_hotkey("f8", lambda: self.hotkey_triggered.emit("mode"))

    def __load_saved_settings(self) -> None:
        """Restore volume, Audio/WWM mode, and the last playlist/selection from disk.

        Only restores the selection (so Play/Next/Previous pick up where you
        left off and the header shows the right title) - it deliberately
        does not mark the row as "now playing" (set_now_playing_row), since
        nothing is actually playing yet at startup.
        """
        settings: AppSettings = load_settings()
        apply_theme(settings.theme)
        self.__now_playing_bar.volume.setValue(settings.volume)
        self.__now_playing_bar.mode_toggle.setChecked(settings.is_audio_mode)
        self.__files = [f for f in settings.playlist if Path(f).exists()]
        if not self.__files:
            return
        self.__current_index = (settings.current_index
                                 if 0 <= settings.current_index < len(self.__files) else 0)
        self.__add_songs()
        self.__songs.widget.setCurrentRow(self.__current_index)
        info: TrackInfo = parse_track_info(Path(self.__files[self.__current_index]).name)
        self.__now_playing_bar.set_header(info.title, info.artist)

    def __save_settings_to_disk(self) -> None:
        """Persist volume, Audio/WWM mode, theme, and the current playlist/selection."""
        save_settings(AppSettings(
            volume=self.__now_playing_bar.volume.value(),
            is_audio_mode=self.__now_playing_bar.mode_toggle.isChecked(),
            playlist=list(self.__files),
            current_index=self.__current_index,
            theme=current_theme(),
        ))

    @Slot(str)
    def __on_hotkey(self, name: str) -> None:
        """Dispatch a global hotkey on the GUI thread.

        Args:
            name: The hotkey action name ("previous", "play", "next", or
                "mode").
        """
        if name == "previous":
            self.__previous_on_click()
        elif name == "play":
            self.__now_playing_bar.play_button.click()
        elif name == "next":
            self.__next_on_click()
        elif name == "mode":
            self.__now_playing_bar.mode_toggle.toggle()

    @Slot(float)
    def __duration_ready(self, duration: float) -> None:
        """Set duration and start the progress poll timer.

        Args:
            duration: The track's total duration in seconds.
        """
        self.__current = -1
        self.__duration = int(duration)
        self.__now_playing_bar.set_duration(self.__duration)
        with contextlib.suppress(AttributeError):
            self.__progress_timer.stop()
        self.__progress_timer = QTimer(self)
        self.__progress_timer.timeout.connect(self.__update_progress)
        self.__progress_timer.start(PROGRESS_POLL_MS)
        self.__update_progress()

    @Slot()
    def __update_progress(self) -> None:
        """Sync the progress bar/time label to the worker's actual playback position.

        Reads Worker.elapsed_seconds() - the same clock the visualizer and
        the playback loop itself use - instead of counting timer ticks,
        which drifts behind real playback since QTimer ticks are never
        exactly 1s apart. Polled faster than once a second so the label
        turns over close to the real second boundary, but only pushed to
        the bar when the whole second actually changes, since each
        setValue() restarts the bar's fill animation.
        """
        if self.__thread is None:
            return
        current: int = min(int(self.__thread.elapsed_seconds()), self.__duration)
        if current != self.__current:
            self.__current = current
            self.__now_playing_bar.set_current_time(current)
        if current >= self.__duration:
            self.__progress_timer.stop()

    @Slot(list)
    def __on_notes_ready(self, events: list[NoteEvent]) -> None:
        """Load the freshly-parsed note events into the visualizer.

        Args:
            events: The note events to visualize, pre-sorted by start time.
        """
        self.__visualizer.load_notes(events, self.__duration)
        self.__visualizer.set_muted_tracks(set(self.__muted_tracks))
        self.__update_visualizer_timer_state()

    @Slot(list)
    def __on_tracks_ready(self, tracks: list[TrackSummary]) -> None:
        """Populate the track panel for the freshly-loaded song.

        Args:
            tracks: The tracks that produced at least one note event.
        """
        self.__loaded_track_indices = {track.index for track in tracks}
        self.__track_list_panel.load_tracks(tracks)

    def __apply_muted_tracks(self) -> None:
        """Push the current mute set to the running Worker (if any) and the visualizer."""
        if self.__thread is not None and self.__thread.isRunning():
            self.__thread.set_muted_tracks(frozenset(self.__muted_tracks))
        self.__visualizer.set_muted_tracks(set(self.__muted_tracks))

    @Slot(int, bool)
    def __on_track_toggled(self, track: int, enabled: bool) -> None:
        """Update one track's mute state; propagate live to the running Worker and visualizer.

        Args:
            track: The MIDI track index whose mute state changed.
            enabled: True if the track should now be audible, False if muted.
        """
        if self.__soloed_track is not None:
            # A manual mute change breaks the "only the soloed track is
            # audible" invariant - drop out of solo rather than leave the
            # solo button showing a state that's no longer true.
            self.__soloed_track = None
            self.__track_list_panel.set_soloed_track(None)
        if enabled:
            self.__muted_tracks.discard(track)
        else:
            self.__muted_tracks.add(track)
        self.__apply_muted_tracks()

    @Slot(int, bool)
    def __on_track_soloed(self, track: int, soloed: bool) -> None:
        """Solo isolates one track by muting every other loaded track.

        Soloing the already-soloed track again (soloed=False, since the
        button is checkable) restores every track to audible instead of
        trying to reconstruct whatever mute set existed before the solo.

        Args:
            track: The MIDI track index that was soloed or unsoloed.
            soloed: True if track should now be the sole audible track,
                False to restore every track to audible.
        """
        self.__soloed_track = track if soloed else None
        self.__muted_tracks = (self.__loaded_track_indices - {track}) if soloed else set()
        self.__track_list_panel.set_muted_tracks(set(self.__muted_tracks))
        self.__track_list_panel.set_soloed_track(self.__soloed_track)
        self.__apply_muted_tracks()

    @Slot()
    def __update_visualizer_position(self) -> None:
        """Push the worker's current playback position into the visualizer."""
        if self.__thread is not None:
            self.__visualizer.set_position(self.__thread.elapsed_seconds())

    def __update_visualizer_timer_state(self) -> None:
        """Run the visualizer's position-poll timer only while a track is active."""
        should_run: bool = self.__thread is not None and self.__thread.isRunning()
        if should_run and not self.__visualizer_timer.isActive():
            self.__visualizer_timer.start(33)
        elif not should_run and self.__visualizer_timer.isActive():
            self.__visualizer_timer.stop()

    @Slot()
    def __on_toast_dismissed(self) -> None:
        """Release the toast once its own fade-out animation has finished hiding it."""
        if self.__toast is None:
            return
        self.__toast.deleteLater()
        self.__toast = None

    def __clear_toast(self) -> None:
        """Immediately remove any current toast, without waiting for its fade-out.

        Used when a new toast (or a successful retry) supersedes the old one
        right away - animating the old one out first would leave it visible,
        briefly overlapping the new one in the same corner.
        """
        if self.__toast is None:
            return
        self.__toast.dismissed.disconnect(self.__on_toast_dismissed)
        self.__toast.hide()
        self.__toast.deleteLater()
        self.__toast = None

    @Slot(str)
    def __show_error(self, msg: str) -> None:
        """Show error message and stop counter.

        Args:
            msg: The error message to display in the toast.
        """
        with contextlib.suppress(AttributeError):
            self.__progress_timer.stop()
        self.__visualizer.clear()
        self.__update_visualizer_timer_state()
        self.__now_playing_bar.reset_progress()
        self.__songs.set_now_playing_row(-1)
        self.__clear_toast()
        self.__toast = Toast(msg, self.__content_widget)
        self.__toast.dismissed.connect(self.__on_toast_dismissed)

    def __get_synth(self) -> tinysoundfont.Synth:
        """Return the shared audio synth, creating and loading it on first use.

        Reused across every track change instead of rebuilt per track, since
        loading the ~420MB SoundFont is the expensive part and it never changes.

        Returns:
            The shared, already-started, already-soundfont-loaded synth.
        """
        if self.__synth is None:
            # tinysoundfont's default gain (0dB) is unity per voice, so dense
            # chords/many simultaneous instruments at high volume can sum
            # past 0dBFS and clip into audible noise/crackling. Negative
            # gain here gives headroom for polyphony, per the library's own
            # guidance ("turn down the gain to avoid clipping").
            self.__synth = tinysoundfont.Synth(gain=SYNTH_GAIN_DB)
            self.__synth.start()
            # sfload's own docs: "If more voices are required than are
            # available, older voices will be cut off" - the 256 default can
            # get exhausted during dense/fast-changing passages (one note
            # may use several internal voices depending on the SoundFont's
            # layering), audibly cutting still-sounding notes. Raise the cap
            # well above what any real MIDI file needs concurrently.
            sfid: int = self.__synth.sfload(self.__soundfont.as_posix(), max_voices=1024)
            self.__synth.program_select(0, sfid, 0, 0)
        return self.__synth

    def __start_playback(self, start_offset: float=0.0) -> None:
        """Start playback, optionally seeking to start_offset seconds into the track.

        Args:
            start_offset: Seconds into the track to seek to before playing.
        """
        if self.__thread and self.__thread.isRunning():
            self.__thread.stop()
            self.__thread.wait()
        # A leftover error from a previous attempt (e.g. WWM mode with the
        # game not running) would otherwise sit on screen for up to
        # DISMISS_AFTER_MS even after this new attempt succeeds.
        self.__clear_toast()
        if start_offset <= 0.0:
            self.__visualizer.clear()
        self.__now_playing_bar.play_button.change.emit(True)
        self.__songs.set_now_playing_row(self.__current_index)
        is_audio: bool = self.__now_playing_bar.mode_toggle.isChecked()
        synth: tinysoundfont.Synth|None = self.__get_synth() if is_audio else None
        self.__thread = Worker(self.__files[self.__current_index], synth, is_audio, start_offset,
                                frozenset(self.__muted_tracks))
        self.__thread.set_volume(self.__now_playing_bar.volume.value())
        self.__thread.duration_ready.connect(self.__duration_ready)
        self.__thread.error.connect(self.__show_error)
        self.__thread.track_ended.connect(self.__on_track_ended)
        self.__thread.notes_ready.connect(self.__on_notes_ready)
        self.__thread.tracks_ready.connect(self.__on_tracks_ready)
        play_button: PlayButton = self.__now_playing_bar.play_button
        self.__thread.finished.connect(lambda: play_button.change.emit(False))
        self.__thread.finished.connect(self.__update_visualizer_timer_state)
        self.__thread.start()
        info: TrackInfo = parse_track_info(Path(self.__files[self.__current_index]).name)
        self.__now_playing_bar.set_header(info.title, info.artist)
        self.__update_visualizer_timer_state()

    def __reset_muted_tracks_if_song_changed(self, previous_index: int) -> None:
        """Clear per-track mute state only on an actual song change, not a same-song restart.

        Comparing indices (rather than clearing unconditionally at every
        "change track" call site) correctly persists mutes both across a
        seek-triggered restart (which never reassigns __current_index at
        all) and across a repeat-wraparound restart of a single-track/
        single-song playlist (where next_track_index() legitimately returns
        the same index).

        Args:
            previous_index: The playlist index that was current before this
                call's track change.
        """
        if previous_index != self.__current_index:
            self.__muted_tracks.clear()
            self.__soloed_track = None

    def __songs_on_double_click(self, item: QListWidgetItem) -> None:
        """Play track when double-clicked in song.

        Args:
            item: The double-clicked song list item.
        """
        previous_index: int = self.__current_index
        self.__current_index = self.__songs.widget.row(item)
        self.__reset_muted_tracks_if_song_changed(previous_index)
        self.__start_playback()

    def __on_search_changed(self, text: str) -> None:
        """Filter songs by search text.

        Args:
            text: The search box's current text.
        """
        needle: str = text.lower()
        songs = self.__songs.widget
        songs.setUpdatesEnabled(False)
        try:
            for i in range(songs.count()):
                item: QListWidgetItem = songs.item(i)
                item.setHidden(needle not in item.text().lower())
        finally:
            songs.setUpdatesEnabled(True)

    def __save_playlist(self) -> None:
        """Save playlist to file."""
        filename, _ = QFileDialog.getSaveFileName(self, "Save Playlist", "", "Playlist (*.m3u)")
        if not filename:
            return
        with Path(filename).open("w", encoding="utf-8") as f:
            for path in self.__files:
                f.write(path + "\n")

    def __add_songs(self) -> None:
        """Rebuild the song list widget from self.__files."""
        if self.__current_index == -1:
            self.__current_index = 0
        self.__songs.widget.clear()
        self.__songs.set_now_playing_row(-1)
        for f in self.__files:
            file_name: str = Path(f).name
            info: TrackInfo = parse_track_info(file_name)
            item: QListWidgetItem = QListWidgetItem(file_name)
            item.setData(TITLE_ROLE, info.title)
            item.setData(ARTIST_ROLE, info.artist)
            self.__songs.widget.addItem(item)
        self.__on_search_changed(self.__search.text())

    def __clear_playlist(self) -> None:
        """Clear the playlist and reset playback state."""
        if self.__thread and self.__thread.isRunning():
            self.__thread.stop()
            self.__thread.wait()
        with contextlib.suppress(AttributeError):
            self.__progress_timer.stop()
        self.__visualizer_timer.stop()
        self.__visualizer.clear()
        self.__track_list_panel.clear()
        self.__muted_tracks.clear()
        self.__soloed_track = None
        self.__loaded_track_indices.clear()
        self.__files.clear()
        self.__current_index = -1
        self.__songs.set_now_playing_row(-1)
        self.__songs.widget.clear()
        self.__now_playing_bar.reset_progress()
        self.__now_playing_bar.set_header("No files loaded")

    def __load_playlist(self) -> None:
        """Load playlist from file."""
        filename, _ = QFileDialog.getOpenFileName(self, "Load Playlist", "", "Playlist (*.m3u)")
        if not filename:
            return
        with Path(filename).open(encoding="utf-8") as f:
            self.__files = [line.strip() for line in f if line.strip()]
        self.__current_index = -1
        self.__add_songs()
        self.__now_playing_bar.set_header(f"Loaded playlist with {len(self.__files)} files.")

    def __browse_on_click(self) -> None:
        """Browse button on click callback: adds files to the current playlist."""
        files, _ = QFileDialog.getOpenFileNames(self, "Open MIDI Files", "",
                                                "MIDI Files (*.mid *.midi)")
        if not files:
            return
        self.__files.extend(files)
        self.__add_songs()
        self.__now_playing_bar.set_header(
            f"Added {len(files)} file(s). Playlist has {len(self.__files)} total.")

    def __previous_on_click(self) -> None:
        """Previous button on click callback."""
        if self.__files and self.__current_index > 0:
            previous_index: int = self.__current_index
            self.__current_index -= 1
            self.__reset_muted_tracks_if_song_changed(previous_index)
            self.__start_playback()

    def __play_on_click(self) -> None:
        """Play button on click callback."""
        if self.__current_index == -1 or not self.__files:
            self.__now_playing_bar.set_header("Please load MIDI files first!")
            self.__now_playing_bar.play_button.change.emit(False)
            return
        if self.__thread and self.__thread.isRunning():
            self.__now_playing_bar.play_button.change.emit(self.__thread.paused)
            self.__thread.toggle_pause()
        else:
            self.__start_playback()

    @Slot(int)
    def __on_seek_requested(self, seconds: int) -> None:
        """Restart playback of the current track from the requested position.

        Args:
            seconds: The playback position to seek to.
        """
        if self.__current_index == -1 or not self.__files:
            return
        self.__start_playback(start_offset=float(seconds))

    def __next_index(self) -> int|None:
        """Return the index to advance to, honoring shuffle/repeat, or None to stop.

        Returns:
            The next playlist index, or None if playback should stop.
        """
        return next_track_index(self.__current_index, len(self.__files),
                                 shuffle=self.__shuffle, repeat=self.__repeat)

    def __next_on_click(self) -> None:
        """Next button on click callback."""
        index: int|None = self.__next_index()
        if index is not None:
            previous_index: int = self.__current_index
            self.__current_index = index
            self.__reset_muted_tracks_if_song_changed(previous_index)
            self.__start_playback()

    @Slot()
    def __on_track_ended(self) -> None:
        """Advance to the next track when the current one finishes on its own."""
        self.__next_on_click()

    def __set_repeat(self, checked: bool) -> None:
        """Toggle repeat-playlist mode.

        Args:
            checked: Whether repeat mode should be enabled.
        """
        self.__repeat = checked

    def __set_shuffle(self, checked: bool) -> None:
        """Toggle shuffle mode.

        Args:
            checked: Whether shuffle mode should be enabled.
        """
        self.__shuffle = checked

    def __set_volume(self, value: int) -> None:
        """Adjust the running worker's master volume.

        Args:
            value: The new master volume, in the MIDI CC7 range (0-127).
        """
        if self.__thread and self.__thread.isRunning():
            self.__thread.set_volume(value)

    def __show_settings(self) -> None:
        """Open Settings dialog."""
        dialog: SettingsDialog = SettingsDialog(self)
        dialog.exec()

    def __show_about(self) -> None:
        """Show about message."""
        QMessageBox.information(self, "About",
                                "MIDI Player for WWM\nBuilt with PySide6 + TinySoundFont")

    def __show_special(self) -> None:
        """Open Special dialog."""
        dialog: SpecialDialog = SpecialDialog(self)
        dialog.exec()

    def __wire_now_playing_bar(self) -> None:
        """Connect the Now Playing bar's buttons/controls to their callbacks."""
        bar: NowPlayingBar = self.__now_playing_bar
        bar.previous_button.clicked.connect(self.__previous_on_click)
        bar.play_button.clicked.connect(self.__play_on_click)
        bar.next_button.clicked.connect(self.__next_on_click)
        bar.shuffle_button.toggled.connect(self.__set_shuffle)
        bar.repeat_button.toggled.connect(self.__set_repeat)
        bar.volume.valueChanged.connect(self.__set_volume)
        bar.seek_requested.connect(self.__on_seek_requested)
        self.__wire_repeat_shuffle_sync()

    def __construct_file_menu(self) -> None:
        """Construct file menu."""
        menu_bar: QMenuBar = self.__menu_bar
        menu: QMenu = menu_bar.addMenu("&File")
        open_action: QAction = QAction("Open MIDI file", self)
        save_action: QAction = QAction("Save Playlist", self)
        load_action: QAction = QAction("Load Playlist", self)
        clear_action: QAction = QAction("Clear Playlist", self)
        exit_action: QAction = QAction("Exit", self)
        open_action.triggered.connect(self.__browse_on_click)
        save_action.triggered.connect(self.__save_playlist)
        load_action.triggered.connect(self.__load_playlist)
        clear_action.triggered.connect(self.__clear_playlist)
        exit_action.triggered.connect(self.close)
        menu.addAction(open_action)
        menu.addAction(save_action)
        menu.addAction(load_action)
        menu.addAction(clear_action)
        menu.addSeparator()
        menu.addAction(exit_action)

    def __construct_playback_menu(self) -> None:
        """Construct playback menu."""
        menu_bar: QMenuBar = self.__menu_bar
        menu: QMenu = menu_bar.addMenu("&Playback")
        previous_action: QAction = QAction("Previous", parent=self)
        play_action: QAction = QAction("Play/Pause", self)
        next_action: QAction = QAction("Next", self)
        self.__repeat_action = QAction("Repeat", self, checkable=True)
        self.__shuffle_action = QAction("Shuffle", self, checkable=True)
        previous_action.triggered.connect(self.__previous_on_click)
        play_action.triggered.connect(self.__play_on_click)
        next_action.triggered.connect(self.__next_on_click)
        menu.addAction(previous_action)
        menu.addAction(play_action)
        menu.addAction(next_action)
        menu.addSeparator()
        menu.addAction(self.__repeat_action)
        menu.addAction(self.__shuffle_action)

    def __wire_repeat_shuffle_sync(self) -> None:
        """Keep the Repeat/Shuffle transport buttons and menu actions in sync."""
        bar: NowPlayingBar = self.__now_playing_bar
        self.__repeat_action.toggled.connect(bar.repeat_button.setChecked)
        bar.repeat_button.toggled.connect(self.__repeat_action.setChecked)
        self.__shuffle_action.toggled.connect(bar.shuffle_button.setChecked)
        bar.shuffle_button.toggled.connect(self.__shuffle_action.setChecked)

    def __construct_setting_menu(self) -> None:
        """Construct settings menu."""
        menu_bar: QMenuBar = self.__menu_bar
        menu: QMenu = menu_bar.addMenu("&Settings")
        settings_action: QAction = QAction("Settings", self)
        settings_action.triggered.connect(self.__show_settings)
        menu.addAction(settings_action)

    def __construct_help_menu(self) -> None:
        """Construct help menu."""
        menu_bar: QMenuBar = self.__menu_bar
        menu: QMenu = menu_bar.addMenu("&Help")
        about_action: QAction = QAction("About", self)
        about_action.triggered.connect(self.__show_about)
        menu.addAction(about_action)

    def __construct_special_menu(self) -> None:
        """Construct special menu."""
        menu_bar: QMenuBar = self.__menu_bar
        menu: QMenu = menu_bar.addMenu("&Special")
        action: QAction = QAction("Thanks", self)
        action.triggered.connect(self.__show_special)
        menu.addAction(action)

    def __construct_menu_bar(self) -> None:
        """Construct menu bar."""
        self.__menu_bar = QMenuBar()
        self.__construct_file_menu()
        self.__construct_playback_menu()
        self.__construct_setting_menu()
        self.__construct_help_menu()
        self.__construct_special_menu()
        self.__style_menu_bar()

    def __style_menu_bar(self) -> None:
        """Apply theme-dependent colors to the menu bar and its dropdown menus."""
        self.__menu_bar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {Colors.BACKGROUND.value.hex};
                color: {Colors.WHITE.value.hex};
                padding: 2px 4px;
                border: none;
            }}
            QMenuBar::item {{
                background: transparent;
                padding: 4px 10px;
                border-radius: {RADIUS_SM}px;
            }}
            QMenuBar::item:selected {{ background-color: {Colors.BACKGROUND_2.value.hex}; }}
            QMenuBar::item:pressed {{ background-color: {Colors.ACCENT_1.value.hex}; }}
            QMenu {{
                background-color: {Colors.BACKGROUND_1.value.hex};
                color: {Colors.WHITE.value.hex};
                border: 1px solid {Colors.BACKGROUND_2.value.hex};
                border-radius: {RADIUS_SM}px;
                padding: 4px;
            }}
            QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: {RADIUS_SM}px; }}
            QMenu::item:selected {{ background-color: {Colors.ACCENT_1.value.hex}; }}
            QMenu::separator {{
                height: 1px;
                background-color: {Colors.BACKGROUND_2.value.hex};
                margin: 4px 8px;
            }}
        """)

    def __construct_songs_section(self) -> Viewer:
        """Construct Songs section.

        Returns:
            The constructed song list viewer.
        """
        self.__songs = Viewer()
        self.__songs.widget.itemDoubleClicked.connect(self.__songs_on_double_click)
        return self.__songs

    def __construct_search(self) -> QLineEdit:
        """Construct the song search box.

        Returns:
            The constructed search box.
        """
        self.__search = SearchBox()
        self.__search.textChanged.connect(self.__on_search_changed)
        return self.__search

    def __construct_songs_page(self) -> QWidget:
        """Construct the Songs page (stack index 0): search box + playlist viewer.

        Returns:
            The assembled Songs page widget.
        """
        page: QWidget = QWidget()
        layout: QVBoxLayout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__construct_search())
        layout.addWidget(self.__construct_songs_section(), stretch=1)
        return page

    def __construct_tracks_page(self) -> TrackListPanel:
        """Construct the Tracks page (stack index 1): per-track mute rows for the current song.

        Returns:
            The constructed track mute/solo panel.
        """
        self.__track_list_panel = TrackListPanel()
        self.__track_list_panel.track_toggled.connect(self.__on_track_toggled)
        self.__track_list_panel.track_soloed.connect(self.__on_track_soloed)
        return self.__track_list_panel

    @staticmethod
    def __tab_button_qss() -> str:
        """Return the checkable tab-button QSS, current as of the active theme.

        Returns:
            The QSS block for a Songs/Tracks tab-style button.
        """
        return f"""
            QPushButton {{
                background: transparent;
                color: {Colors.TEXT_MUTED.value.hex};
                border: none;
                border-bottom: 2px solid transparent;
                padding: 4px 2px;
            }}
            QPushButton:checked {{
                color: {Colors.WHITE.value.hex};
                border-bottom: 2px solid {Colors.ACCENT_1.value.hex};
            }}
        """

    def __make_tab_button(self, text: str) -> QPushButton:
        """Construct a checkable tab-style button for the Songs/Tracks switch.

        Args:
            text: The button's label text.

        Returns:
            The constructed, styled tab button.
        """
        button: QPushButton = QPushButton(text)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(self.__tab_button_qss())
        return button

    def __style_tab_buttons(self) -> None:
        """Re-apply the tab-button QSS to the Songs/Tracks buttons after a theme switch."""
        qss: str = self.__tab_button_qss()
        for button in self.__playlist_tab_group.buttons():
            button.setStyleSheet(qss)

    def __construct_tab_row(self) -> QHBoxLayout:
        """Construct the Songs/Tracks tab switch driving self.__stacked_playlist.

        Returns:
            The assembled tab row layout.
        """
        songs_button: QPushButton = self.__make_tab_button("Songs")
        tracks_button: QPushButton = self.__make_tab_button("Tracks")
        songs_button.setChecked(True)
        self.__playlist_tab_group = QButtonGroup(self)
        self.__playlist_tab_group.setExclusive(True)
        self.__playlist_tab_group.addButton(songs_button, 0)
        self.__playlist_tab_group.addButton(tracks_button, 1)
        self.__playlist_tab_group.idClicked.connect(self.__stacked_playlist.setCurrentIndex)
        layout: QHBoxLayout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_XS)
        layout.addWidget(songs_button)
        layout.addWidget(tracks_button)
        layout.addStretch()
        return layout

    def __construct_playlist(self) -> QVBoxLayout:
        """Construct playlist section: tab switch above a Songs/Tracks stacked view.

        Returns:
            The assembled playlist column layout.
        """
        self.__stacked_playlist = QStackedLayout()
        self.__stacked_playlist.addWidget(self.__construct_songs_page())
        self.__stacked_playlist.addWidget(self.__construct_tracks_page())
        layout: QVBoxLayout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)
        layout.addLayout(self.__construct_tab_row())
        layout.addLayout(self.__stacked_playlist, stretch=1)
        return layout

    def __construct_content_row(self) -> QHBoxLayout:
        """Construct the split row: playlist on the left, visualizer on the right.

        Returns:
            The assembled content row layout.
        """
        self.__visualizer = PianoVisualizer()
        layout: QHBoxLayout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)
        layout.addLayout(self.__construct_playlist(), stretch=1)
        layout.addWidget(self.__visualizer, stretch=2)
        return layout

    def __style_root(self) -> None:
        """Apply the base window background to the otherwise-unstyled root/content widgets.

        Both are plain QWidgets (not QFrame), so WA_StyledBackground is
        required for their background-color QSS to paint at all - without
        it, these regions (window margins, gaps between panels) would keep
        showing Qt's default palette instead of following the app's theme.
        """
        style: str = f"background-color: {Colors.BACKGROUND.value.hex};"
        self.__root.setStyleSheet(style)
        self.__content_widget.setStyleSheet(style)

    def __construct_layout(self) -> None:
        """Construct layout."""
        self.__root: QWidget = QWidget()
        self.__root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(self.__root)
        root_layout: QVBoxLayout = QVBoxLayout(self.__root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        icon: QIcon = QIcon(resource_path("src/input/logo.ico").as_posix())
        self.__title_bar = TitleBar(self, "WWM MIDI Player", icon)
        root_layout.addWidget(self.__title_bar)
        root_layout.addWidget(self.__menu_bar)
        self.__content_widget = QWidget()
        self.__content_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.__central_layout = QVBoxLayout(self.__content_widget)
        self.__central_layout.setContentsMargins(SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD)
        self.__central_layout.setSpacing(SPACING_MD)
        self.__central_layout.addLayout(self.__construct_content_row(), stretch=1)
        root_layout.addWidget(self.__content_widget, stretch=1)
        self.__visualizer_timer = QTimer(self)
        # PreciseTimer: Qt's default coarse timer can drift/coalesce by tens of
        # milliseconds on Windows, which reads as visible stutter in the falling
        # notes at a 33ms tick rate.
        self.__visualizer_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.__visualizer_timer.timeout.connect(self.__update_visualizer_position)
        self.__now_playing_bar = NowPlayingBar()
        root_layout.addWidget(self.__now_playing_bar)
        self.__style_root()

    def __cursor_for_edges(self, edges: Qt.Edge) -> Qt.CursorShape:
        """Map a resize-edge combination to the appropriate resize cursor shape.

        Args:
            edges: The window edge(s) the cursor is currently near.

        Returns:
            The cursor shape matching that edge combination.
        """
        if edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        if edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.ArrowCursor

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update cursor shape and pending resize edges based on proximity to window edges.

        Args:
            event: The Qt mouse move event.
        """
        if self.isMaximized():
            self.__resize_edges = Qt.Edge(0)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)
            return
        pos: QPoint = event.position().toPoint()
        self.__resize_edges = compute_resize_edges((pos.x(), pos.y()),
                                                    (self.width(), self.height()), RESIZE_MARGIN)
        self.setCursor(self.__cursor_for_edges(self.__resize_edges))
        super().mouseMoveEvent(event)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start an OS-native resize if the press is near a window edge.

        Args:
            event: The Qt mouse press event.
        """
        if self.__resize_edges != Qt.Edge(0) and event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemResize(self.__resize_edges)
                return
        super().mousePressEvent(event)

    @override
    def changeEvent(self, event: QEvent) -> None:
        """Sync the title bar's maximize button with the actual window state.

        Args:
            event: The Qt change event.
        """
        if event.type() == QEvent.Type.WindowStateChange:
            self.__title_bar.set_maximized(self.isMaximized())
        super().changeEvent(event)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep a visible toast anchored to the top-right corner as the window resizes.

        Args:
            event: The Qt resize event.
        """
        if self.__toast is not None:
            self.__toast.reposition()
        super().resizeEvent(event)

    @override
    def closeEvent(self, event: QCloseEvent, /) -> None:
        """Persist settings and tear down the running worker/synth on window close.

        Args:
            event: The Qt close event.
        """
        self.__save_settings_to_disk()
        if self.__thread and self.__thread.isRunning():
            self.__thread.stop()
            self.__thread.wait()
        self.__visualizer_timer.stop()
        if self.__synth is not None:
            self.__synth.stop()
        return super().closeEvent(event)

def main() -> None:
    """Launch the app; also the `wwm-player` console script entry point."""
    app: QApplication = QApplication(sys.argv)
    app.setApplicationName("WWM MIDI Player")
    icon: Path = resource_path("src/input/logo.ico")
    app.setWindowIcon(QIcon(icon.as_posix()))
    window: Player = Player()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
