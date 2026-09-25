"""Pure per-song analysis for the playlist: length, instrument count, and WWM playability.

WWM's instrument only covers MIDI notes NOTE_MIN..NOTE_MAX (48-83); anything
outside is octave-folded into that range (utils.wwm_macro.fold_note), which
keeps the note name but not its octave. playable_fraction() measures how much
of a song survives unfolded, and best_transpose() finds the semitone shift
that keeps the most of it in range.
"""

from collections import Counter
from dataclasses import dataclass

import mido

from utils.midi_timing import calculate_duration
from utils.wwm_macro import NOTE_MAX, NOTE_MIN

MAX_TRANSPOSE: int = 24


@dataclass(frozen=True, slots=True)
class SongAnalysis:
    """What the playlist shows about a song before it's played.

    Attributes:
        duration: Length in seconds.
        track_count: Number of tracks that sound at least one note.
        pitches: Every sounded note_on's MIDI note number, in file order.
    """

    duration: float
    track_count: int
    pitches: tuple[int, ...]


def analyze_midi(midi: mido.MidiFile) -> SongAnalysis:
    """Analyze an already-parsed MIDI file.

    Args:
        midi: The parsed MIDI file.

    Returns:
        The file's duration, sounding track count, and note pitches.
    """
    pitches: list[int] = []
    track_count: int = 0
    for track in midi.tracks:
        sounded: bool = False
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                pitches.append(msg.note)
                sounded = True
        track_count += sounded
    return SongAnalysis(calculate_duration(midi), track_count, tuple(pitches))


def analyze_song(path: str) -> SongAnalysis:
    """Parse and analyze a MIDI file on disk.

    Args:
        path: The MIDI file to analyze.

    Returns:
        The file's analysis.
    """
    return analyze_midi(mido.MidiFile(path))


def transposed(note: int, semitones: int) -> int:
    """Shift a MIDI note by semitones, clamped to the valid 0-127 range.

    Args:
        note: The MIDI note number.
        semitones: The shift, positive (up) or negative (down).

    Returns:
        The shifted, clamped note number.
    """
    return max(0, min(127, note + semitones))


def playable_fraction(pitches: tuple[int, ...], transpose: int=0,
                      low: int=NOTE_MIN, high: int=NOTE_MAX) -> float:
    """Return the fraction of notes that land inside [low, high] after transposing.

    Args:
        pitches: The song's sounded note numbers.
        transpose: Semitones applied before checking the range.
        low: Lowest playable note, inclusive.
        high: Highest playable note, inclusive.

    Returns:
        0.0-1.0; 1.0 for a song with no notes (nothing gets folded).
    """
    if not pitches:
        return 1.0
    inside: int = sum(1 for note in pitches if low <= transposed(note, transpose) <= high)
    return inside / len(pitches)


def best_transpose(pitches: tuple[int, ...], low: int=NOTE_MIN, high: int=NOTE_MAX,
                   limit: int=MAX_TRANSPOSE) -> int:
    """Return the shift in [-limit, limit] that keeps the most notes in [low, high].

    Ties prefer the smallest shift (so a song that already fits stays put),
    then shifting up. Counts via a pitch histogram, so it's O(shifts x 128)
    rather than O(shifts x notes).

    Args:
        pitches: The song's sounded note numbers.
        low: Lowest playable note, inclusive.
        high: Highest playable note, inclusive.
        limit: Largest shift to consider, in either direction.

    Returns:
        The best semitone shift.
    """
    histogram: Counter[int] = Counter(pitches)

    def inside(shift: int) -> int:
        return sum(count for note, count in histogram.items()
                   if low <= transposed(note, shift) <= high)

    return max(range(-limit, limit + 1), key=lambda shift: (inside(shift), -abs(shift), shift))
