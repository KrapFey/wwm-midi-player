"""Tests for per-song analysis: duration/track count, WWM playable range, auto-transpose."""

import mido

from utils.song_analysis import (
    analyze_midi,
    best_transpose,
    playable_fraction,
    transposed,
)


def _midi(tracks: list[list[int]]) -> mido.MidiFile:
    midi = mido.MidiFile(ticks_per_beat=480)
    for notes in tracks:
        track = mido.MidiTrack()
        for note in notes:
            track.append(mido.Message("note_on", note=note, velocity=90, time=0))
            track.append(mido.Message("note_off", note=note, velocity=0, time=480))
        midi.tracks.append(track)
    return midi


def test_analyze_counts_only_tracks_that_sound() -> None:
    midi = _midi([[60, 62], [], [72]])
    midi.tracks[1].append(mido.MetaMessage("track_name", name="conductor"))
    analysis = analyze_midi(midi)
    assert analysis.track_count == 2
    assert analysis.pitches == (60, 62, 72)
    assert analysis.duration == 1.0  # tracks play in parallel: longest is two 0.5s notes


def test_analyze_ignores_zero_velocity_note_on() -> None:
    midi = _midi([[60]])
    midi.tracks[0].append(mido.Message("note_on", note=90, velocity=0, time=0))
    assert analyze_midi(midi).pitches == (60,)


def test_transposed_clamps_to_midi_range() -> None:
    assert transposed(60, 5) == 65
    assert transposed(125, 10) == 127
    assert transposed(3, -10) == 0


def test_playable_fraction_counts_notes_inside_wwm_range() -> None:
    assert playable_fraction((48, 83, 47, 84)) == 0.5
    assert playable_fraction((47, 84), transpose=1, low=48, high=85) == 1.0


def test_playable_fraction_of_empty_song_is_full() -> None:
    assert playable_fraction(()) == 1.0


def test_best_transpose_keeps_fitting_song_in_place() -> None:
    assert best_transpose((60, 64, 67)) == 0


def test_best_transpose_shifts_high_song_down_into_range() -> None:
    shift = best_transpose((90, 95, 100))
    assert playable_fraction((90, 95, 100), shift) == 1.0
    assert shift == -17  # smallest shift that brings 100 down to 83


def test_best_transpose_prefers_smallest_shift_on_ties() -> None:
    # 47 fits after +1..+36; the smallest is chosen.
    assert best_transpose((47,)) == 1
