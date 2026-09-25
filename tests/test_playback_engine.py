"""Tests for the playback engine, driven with a recording fake synth.

Songs are a few ticks long (default 120 BPM, 480 ticks/beat -> 48 ticks is
50ms), so each test plays in real time in well under a second.
"""

import threading
from pathlib import Path

import mido

from utils.playback_engine import PlaybackCallbacks, PlaybackEngine

STEP_TICKS = 48


class FakeSynth:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def noteon(self, channel: int, note: int, velocity: int) -> None:
        self.calls.append(("noteon", channel, note, velocity))

    def noteoff(self, channel: int, note: int) -> None:
        self.calls.append(("noteoff", channel, note))

    def control_change(self, channel: int, control: int, value: int) -> None:
        self.calls.append(("cc", channel, control, value))

    def program_change(self, channel: int, program: int, is_drums: bool = False) -> None:
        self.calls.append(("program", channel, program, is_drums))

    def notes_on(self) -> list[int]:
        return [call[2] for call in self.calls if call[0] == "noteon"]


def _write_midi(path: Path, tracks: list[list[int]], cc7: int|None = None) -> str:
    """Write one MIDI track per list of notes, each note STEP_TICKS long, back to back."""
    midi = mido.MidiFile(ticks_per_beat=480)
    for index, notes in enumerate(tracks):
        track = mido.MidiTrack()
        if cc7 is not None and index == 0:
            track.append(mido.Message("control_change", channel=0, control=7, value=cc7, time=0))
        for note in notes:
            track.append(mido.Message("note_on", channel=index, note=note, velocity=90, time=0))
            track.append(mido.Message("note_off", channel=index, note=note, velocity=0,
                                      time=STEP_TICKS))
        midi.tracks.append(track)
    midi.save(path)
    return str(path)


def _events_recorder() -> tuple[PlaybackCallbacks, list[tuple]]:
    events: list[tuple] = []
    callbacks = PlaybackCallbacks(
        on_duration=lambda seconds: events.append(("duration", seconds)),
        on_notes=lambda notes: events.append(("notes", len(notes))),
        on_tracks=lambda tracks: events.append(("tracks", [t.index for t in tracks])),
        on_error=lambda message: events.append(("error", message)),
        on_ended=lambda: events.append(("ended",)),
    )
    return callbacks, events


def test_plays_every_note_and_reports_progress_in_order(tmp_path: Path) -> None:
    path = _write_midi(tmp_path / "song.mid", [[60, 62, 64]])
    synth = FakeSynth()
    callbacks, events = _events_recorder()
    PlaybackEngine(path, synth, is_audio=True, callbacks=callbacks).run()
    assert synth.notes_on() == [60, 62, 64]
    assert [event[0] for event in events] == ["duration", "notes", "tracks", "ended"]
    assert events[1] == ("notes", 3)
    assert events[2] == ("tracks", [0])


def test_muted_track_is_silent_but_note_offs_still_forwarded(tmp_path: Path) -> None:
    path = _write_midi(tmp_path / "song.mid", [[60], [72]])
    synth = FakeSynth()
    PlaybackEngine(path, synth, is_audio=True, muted_tracks=frozenset({1})).run()
    assert synth.notes_on() == [60]
    assert ("noteoff", 1, 72) in synth.calls


def test_start_offset_skips_earlier_notes(tmp_path: Path) -> None:
    path = _write_midi(tmp_path / "song.mid", [[60, 62, 64, 65]])
    synth = FakeSynth()
    engine = PlaybackEngine(path, synth, is_audio=True, start_offset=0.1)
    assert engine.elapsed_seconds() == 0.1
    engine.run()
    assert synth.notes_on() == [64, 65]


def test_stop_prevents_natural_end(tmp_path: Path) -> None:
    path = _write_midi(tmp_path / "song.mid", [[60] * 40])
    callbacks, events = _events_recorder()
    engine = PlaybackEngine(path, FakeSynth(), is_audio=True, callbacks=callbacks)
    thread = threading.Thread(target=engine.run)
    thread.start()
    engine.stop()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert ("ended",) not in events


def test_unreadable_file_reports_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.mid"
    path.write_bytes(b"not a midi file")
    callbacks, events = _events_recorder()
    PlaybackEngine(str(path), FakeSynth(), is_audio=True, callbacks=callbacks).run()
    assert events[0][0] == "error"
    assert ("ended",) not in events


def test_master_volume_scales_file_channel_volume(tmp_path: Path) -> None:
    path = _write_midi(tmp_path / "song.mid", [[60]], cc7=100)
    synth = FakeSynth()
    engine = PlaybackEngine(path, synth, is_audio=True)
    engine.set_volume(127 // 2)
    engine.run()
    assert ("cc", 0, 7, 100 * (127 // 2) // 127) in synth.calls


def test_transpose_shifts_sounded_notes_and_reported_events(tmp_path: Path) -> None:
    path = _write_midi(tmp_path / "song.mid", [[60, 62]])
    synth = FakeSynth()
    reported: list[int] = []
    callbacks = PlaybackCallbacks(on_notes=lambda notes: reported.extend(n.note for n in notes))
    PlaybackEngine(path, synth, is_audio=True, callbacks=callbacks, transpose=-12).run()
    assert synth.notes_on() == [48, 50]
    assert ("noteoff", 0, 48) in synth.calls
    assert reported == [48, 50]


def _long_rest_midi(path: Path) -> str:
    """One note, a 3-second rest, then another note (default 120 BPM: 480 ticks = 0.5s)."""
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=48))
    track.append(mido.Message("note_on", note=72, velocity=90, time=480 * 6))
    track.append(mido.Message("note_off", note=72, velocity=0, time=48))
    midi.tracks.append(track)
    midi.save(path)
    return str(path)


def _start(engine: PlaybackEngine) -> threading.Thread:
    thread = threading.Thread(target=engine.run, daemon=True)
    thread.start()
    return thread


def test_pause_freezes_position_immediately_even_mid_rest(tmp_path: Path) -> None:
    import time
    synth = FakeSynth()
    engine = PlaybackEngine(_long_rest_midi(tmp_path / "rest.mid"), synth, is_audio=True)
    thread = _start(engine)
    time.sleep(0.4)
    engine.toggle_pause()
    paused_at = engine.elapsed_seconds()
    assert 0.3 < paused_at < 0.55
    time.sleep(0.5)
    assert engine.elapsed_seconds() == paused_at  # no creeping while paused
    engine.toggle_pause()
    time.sleep(0.2)
    assert paused_at + 0.1 < engine.elapsed_seconds() < paused_at + 0.35  # resumes from there
    engine.stop()
    thread.join(timeout=2)


def test_pause_mid_rest_holds_back_the_next_note(tmp_path: Path) -> None:
    import time
    synth = FakeSynth()
    engine = PlaybackEngine(_long_rest_midi(tmp_path / "rest.mid"), synth, is_audio=True)
    thread = _start(engine)
    time.sleep(0.3)
    engine.toggle_pause()
    time.sleep(3.2)  # past the second note's scheduled time (3.05s)
    assert synth.notes_on() == [60]
    engine.stop()
    thread.join(timeout=2)


def test_stop_mid_rest_returns_promptly(tmp_path: Path) -> None:
    import time
    engine = PlaybackEngine(_long_rest_midi(tmp_path / "rest.mid"), FakeSynth(), is_audio=True)
    thread = _start(engine)
    time.sleep(0.3)
    stopped = time.perf_counter()
    engine.stop()
    thread.join(timeout=5)
    assert time.perf_counter() - stopped < 0.15


def test_clock_only_advances_once_loaded_and_reports_its_start(tmp_path: Path) -> None:
    started: list[float] = []
    engine = PlaybackEngine(_write_midi(tmp_path / "song.mid", [[60, 62]]), FakeSynth(),
                            is_audio=True, start_offset=0.05,
                            callbacks=PlaybackCallbacks(on_clock_started=started.append))
    assert not engine.advancing  # not loaded yet: the position is frozen
    engine.run()
    assert started == [0.05]


def test_paused_engine_does_not_advance(tmp_path: Path) -> None:
    import time
    engine = PlaybackEngine(_long_rest_midi(tmp_path / "rest.mid"), FakeSynth(), is_audio=True)
    thread = _start(engine)
    time.sleep(0.2)
    assert engine.advancing
    engine.toggle_pause()
    assert not engine.advancing
    engine.stop()
    thread.join(timeout=2)


def test_resume_continues_from_pause_position_immediately(tmp_path: Path) -> None:
    import time
    engine = PlaybackEngine(_long_rest_midi(tmp_path / "rest.mid"), FakeSynth(), is_audio=True)
    thread = _start(engine)
    time.sleep(0.3)
    engine.toggle_pause()
    paused_at = engine.elapsed_seconds()
    time.sleep(0.8)
    engine.toggle_pause()
    # Read right away, before the playback thread has noticed the resume: the
    # paused time must not be counted as played.
    assert abs(engine.elapsed_seconds() - paused_at) < 0.01
    engine.stop()
    thread.join(timeout=2)
