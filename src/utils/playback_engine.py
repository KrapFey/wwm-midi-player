"""The MIDI playback engine: real-time playback through the synth or the game.

PlaybackEngine owns one MIDI file's real-time playback loop. It is UI-agnostic:
it reports progress through PlaybackCallbacks, and run() is a plain blocking
call that web.api.Api runs on its own threading.Thread.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import mido
import tinysoundfont
import win32gui

from utils.midi_timing import calculate_duration
from utils.note_events import (
    DRUM_CHANNEL,
    NoteEvent,
    TrackSummary,
    build_note_events,
    summarize_tracks,
)
from utils.playback_stream import PlaybackMessage, build_playback_messages
from utils.song_analysis import transposed
from utils.wwm_macro import KeyManager

# Headroom (relative dB) applied to the shared synth's output so dense
# chords/many simultaneous channels at high volume don't sum past 0dBFS.
SYNTH_GAIN_DB: float = -6.0
# sfload's own docs: "If more voices are required than are available, older
# voices will be cut off" - the 256 default can get exhausted during dense/
# fast-changing passages (one note may use several internal voices depending
# on the SoundFont's layering), audibly cutting still-sounding notes. Raised
# well above what any real MIDI file needs concurrently.
SYNTH_MAX_VOICES: int = 1024
GAME_WINDOW_TITLE: str = "Where Winds Meet"


def create_synth(soundfont: Path) -> tinysoundfont.Synth:
    """Create, start, and load the shared audio synth.

    Loading the ~420MB SoundFont is the expensive part, so front ends create
    this once and reuse it across every track.

    Args:
        soundfont: Path to the .sf2 SoundFont to load.

    Returns:
        The started, soundfont-loaded synth.
    """
    # tinysoundfont's default gain (0dB) is unity per voice, so dense chords/
    # many simultaneous instruments at high volume can sum past 0dBFS and clip
    # into audible noise/crackling. Negative gain here gives headroom for
    # polyphony, per the library's own guidance ("turn down the gain to avoid
    # clipping").
    synth: tinysoundfont.Synth = tinysoundfont.Synth(gain=SYNTH_GAIN_DB)
    synth.start()
    sfid: int = synth.sfload(soundfont.as_posix(), max_voices=SYNTH_MAX_VOICES)
    synth.program_select(0, sfid, 0, 0)
    return synth


def _ignore(*_args: object) -> None:
    """Default no-op callback."""


@dataclass(frozen=True, slots=True)
class PlaybackCallbacks:
    """Progress notifications from PlaybackEngine.run(), all called on the engine's thread.

    Attributes:
        on_duration: The song's total duration in seconds, once parsed.
        on_notes: Every note event (for a visualizer), once parsed.
        on_tracks: The tracks that produced notes (for a mute panel), once parsed.
        on_error: A user-facing error message; playback stops afterward.
        on_ended: The song finished on its own (not stopped/errored).
    """

    on_duration: Callable[[float], None] = field(default=_ignore)
    on_notes: Callable[[list[NoteEvent]], None] = field(default=_ignore)
    on_tracks: Callable[[list[TrackSummary]], None] = field(default=_ignore)
    on_error: Callable[[str], None] = field(default=_ignore)
    on_ended: Callable[[], None] = field(default=_ignore)


class PlaybackEngine:
    """Plays one MIDI file in real time through the synth (Audio) or the game (WWM)."""

    def __init__(self, filename: str, synth: tinysoundfont.Synth|None,
                      is_audio: bool=False, start_offset: float=0.0,
                      muted_tracks: frozenset[int]=frozenset(),
                      callbacks: PlaybackCallbacks|None=None, transpose: int=0) -> None:
        """Initialize the engine.

        synth is a shared, already-started, already-soundfont-loaded Synth
        owned by the front end and reused across tracks (required when
        is_audio); the engine never loads a SoundFont or tears the synth
        down itself, since reloading the ~420MB .sf2 on every track change is
        the expensive part.

        start_offset seeks to that many seconds into the song: run() fast-
        forwards through messages up to that point (still applying
        program/control changes so instrument state is correct) without
        actually sounding notes or sleeping, then resumes normal playback.

        muted_tracks is the initial set of MIDI track indices to silence;
        set_muted_tracks() updates it live while the engine is running.

        transpose shifts every note by that many semitones - in both modes,
        so Audio mode previews what WWM mode will press - and the note events
        reported to on_notes are shifted to match.

        Args:
            filename: Path to the MIDI file to play.
            synth: Shared audio synth to play through, or None in WWM mode.
            is_audio: True for Audio mode (synth), False for WWM mode
                (simulated keypresses).
            start_offset: Seconds into the song to seek to before playing.
            muted_tracks: MIDI track indices to silence from the start.
            callbacks: Progress notifications; all default to no-ops.
            transpose: Semitones to shift every note by (0 = as written).
        """
        self.__is_audio: bool = is_audio
        self.__filename: str = filename
        self.__synth: tinysoundfont.Synth|None = synth
        self.__callbacks: PlaybackCallbacks = callbacks or PlaybackCallbacks()
        self.__transpose: int = transpose
        # Only WWM mode sends keys; don't touch the keybindings file otherwise.
        self.__key_manager: KeyManager|None = None if is_audio else KeyManager()
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
        in this class. Front ends always hand in a fresh frozenset, so a read
        here mid-swap always sees one fully-formed set or the other.

        Args:
            tracks: The MIDI track indices that should now be muted.
        """
        self.__muted_tracks = tracks

    def elapsed_seconds(self) -> float:
        """Return seconds elapsed in the current song, frozen while paused.

        Safe to call from another thread while run() is executing: mirrors
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
        note: int = transposed(msg.note, self.__transpose)
        if msg.type == "note_on" and msg.velocity > 0:
            if track not in self.__muted_tracks:
                chord_notes.append((msg.channel, note, msg.velocity))
        elif msg.type == "note_off" and self.__is_audio:
            synth.noteoff(msg.channel, note)

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

    def run(self) -> None:
        """Play the file to the end (or until stop()), with chord grouping and tempo handling.

        Blocking; call it on a dedicated thread.
        """
        try:
            player: mido.MidiFile = mido.MidiFile(self.__filename)
        except mido.midifiles.meta.KeySignatureError:
            self.__callbacks.on_error("Invalid MIDI File.\nPlease select valid MIDI file.")
            return
        except Exception as exc:  # noqa: BLE001 - surface any parse failure to the UI
            self.__callbacks.on_error(f"Failed to load MIDI file.\n{exc}")
            return
        synth: tinysoundfont.Synth|None = self.__synth
        handle: int = 0
        if not self.__is_audio:
            handle = win32gui.FindWindow(None, GAME_WINDOW_TITLE)
            if not handle:
                self.__callbacks.on_error(f"{GAME_WINDOW_TITLE} is not running.\n"
                                          "Please run the game then try again.")
                return
        elif synth is not None:
            # GM channel 10 (0-indexed 9) defaults to a drum kit even when the
            # file never sends an explicit program_change for it.
            synth.program_change(DRUM_CHANNEL, 0, is_drums=True)
        tick_events: list[tuple[int, mido.Message]] = []
        natural_end: bool = True
        try:
            self.__callbacks.on_duration(calculate_duration(player))
            events: list[NoteEvent] = build_note_events(player)
            if self.__transpose:
                events = [replace(event, note=transposed(event.note, self.__transpose))
                          for event in events]
            self.__callbacks.on_notes(events)
            self.__callbacks.on_tracks(summarize_tracks(player, events))
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
            self.__callbacks.on_error(f"Playback error.\n{exc}")
        finally:
            # Silence any lingering notes without tearing down the shared,
            # already-loaded synth - it's reused by the next track.
            if self.__is_audio and synth is not None:
                for channel in range(16):
                    synth.control_change(channel, 123, 0)
        if natural_end:
            self.__callbacks.on_ended()

    def stop(self) -> None:
        """Stop playback; run() returns shortly after."""
        self.__running = False

    def toggle_pause(self) -> None:
        """Pause or resume playback."""
        self.__paused = not self.__paused

    def set_volume(self, volume: int) -> None:
        """Set the master volume.

        Args:
            volume: The new master volume, in the MIDI CC7 range (0-127).
        """
        self.__volume = volume
