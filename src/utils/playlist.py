"""Pure playlist logic: shuffle/repeat navigation, index bookkeeping, and .m3u files."""

import random
from pathlib import Path

MIDI_SUFFIXES: frozenset[str] = frozenset({".mid", ".midi"})


def next_track_index(current_index: int, count: int, *, shuffle: bool, repeat: bool) -> int | None:
    """Return the next playlist index to play, or None if playback should stop.

    Args:
        current_index: Index of the currently playing track.
        count: Total number of tracks in the playlist.
        shuffle: Pick a random track other than the current one.
        repeat: Wrap around to the start (or replay a single track) at the end.

    Returns:
        The next index to play, or None when there is nothing left to play.
    """
    if not count:
        return None
    if shuffle:
        if count == 1:
            return 0 if repeat else None
        candidates: list[int] = [i for i in range(count) if i != current_index]
        return random.choice(candidates)
    if current_index < count - 1:
        return current_index + 1
    return 0 if repeat else None


def index_after_move(index: int, source: int, target: int) -> int:
    """Return where the entry at index ends up after moving source to target.

    Args:
        index: An index being tracked (e.g. the selected or playing song), or -1.
        source: The index of the entry being moved.
        target: The index it's moved to (its index after the move).

    Returns:
        The tracked entry's new index (-1 stays -1).
    """
    if index < 0:
        return index
    if index == source:
        return target
    if source < index <= target:
        return index - 1
    if target <= index < source:
        return index + 1
    return index


def index_after_removal(index: int, removed: int) -> int:
    """Return where the entry at index ends up after removing another entry.

    Args:
        index: An index being tracked, or -1. Must not equal removed.
        removed: The index of the entry being removed.

    Returns:
        The tracked entry's new index (-1 stays -1).
    """
    return index - 1 if index > removed else index


def expand_midi_paths(paths: list[str]) -> list[str]:
    """Return every MIDI file among paths, expanding folders (recursively, sorted).

    Args:
        paths: Files and/or folders, e.g. from a drag-and-drop.

    Returns:
        The MIDI files found, in the order given (folder contents sorted).
    """
    found: list[str] = []
    for path in map(Path, paths):
        if path.is_dir():
            found.extend(str(child) for child in sorted(path.rglob("*"))
                         if child.is_file() and child.suffix.lower() in MIDI_SUFFIXES)
        elif path.suffix.lower() in MIDI_SUFFIXES:
            found.append(str(path))
    return found


def write_m3u(path: Path, files: list[str]) -> None:
    """Save a playlist as an .m3u file: one path per line.

    Args:
        path: Where to write the playlist.
        files: The playlist's file paths, in order.
    """
    path.write_text("".join(f"{file}\n" for file in files), encoding="utf-8")


def read_m3u(path: Path) -> list[str]:
    """Load an .m3u playlist, skipping blank lines and #-comments (e.g. #EXTM3U).

    Args:
        path: The playlist file to read.

    Returns:
        The playlist's file paths, in order.
    """
    lines: list[str] = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]
