"""Tests for playlist next-track resolution (shuffle/repeat)."""

from utils.playlist import next_track_index


def test_empty_playlist_returns_none() -> None:
    assert next_track_index(0, 0, shuffle=False, repeat=False) is None


def test_linear_advance() -> None:
    assert next_track_index(0, 3, shuffle=False, repeat=False) == 1


def test_linear_stops_at_end_without_repeat() -> None:
    assert next_track_index(2, 3, shuffle=False, repeat=False) is None


def test_linear_wraps_at_end_with_repeat() -> None:
    assert next_track_index(2, 3, shuffle=False, repeat=True) == 0


def test_shuffle_never_repeats_current_track() -> None:
    for _ in range(50):
        index = next_track_index(1, 3, shuffle=True, repeat=False)
        assert index in (0, 2)


def test_shuffle_single_track_without_repeat_stops() -> None:
    assert next_track_index(0, 1, shuffle=True, repeat=False) is None


def test_shuffle_single_track_with_repeat_replays_it() -> None:
    assert next_track_index(0, 1, shuffle=True, repeat=True) == 0


def test_index_after_move_tracks_moved_entry_and_shifts_between() -> None:
    from utils.playlist import index_after_move
    # Move entry 1 to 3: [a, B, c, d] -> [a, c, d, B]
    assert [index_after_move(i, 1, 3) for i in range(4)] == [0, 3, 1, 2]
    # Move entry 3 to 0: [a, b, c, D] -> [D, a, b, c]
    assert [index_after_move(i, 3, 0) for i in range(4)] == [1, 2, 3, 0]
    assert index_after_move(-1, 0, 2) == -1


def test_index_after_removal_shifts_later_entries() -> None:
    from utils.playlist import index_after_removal
    assert [index_after_removal(i, 1) for i in (0, 2, 3)] == [0, 1, 2]
    assert index_after_removal(-1, 0) == -1


def test_expand_midi_paths_expands_folders_and_filters_types(tmp_path) -> None:
    from utils.playlist import expand_midi_paths
    (tmp_path / "album" / "disc2").mkdir(parents=True)
    for name in ("album/b.mid", "album/a.MIDI", "album/disc2/c.mid", "album/cover.jpg", "x.mid"):
        (tmp_path / name).write_bytes(b"")
    found = expand_midi_paths([str(tmp_path / "x.mid"), str(tmp_path / "album"),
                               str(tmp_path / "album" / "cover.jpg")])
    names = [p.replace(str(tmp_path), "").replace("\\", "/") for p in found]
    assert names == ["/x.mid", "/album/a.MIDI", "/album/b.mid", "/album/disc2/c.mid"]


def test_m3u_round_trip_skips_comments_and_blank_lines(tmp_path) -> None:
    from utils.playlist import read_m3u, write_m3u
    path = tmp_path / "list.m3u"
    write_m3u(path, ["C:/music/a.mid", "C:/music/b c.mid"])
    assert read_m3u(path) == ["C:/music/a.mid", "C:/music/b c.mid"]
    path.write_text("#EXTM3U\n\nC:/a.mid\n# comment\n  C:/b.mid  \n", encoding="utf-8")
    assert read_m3u(path) == ["C:/a.mid", "C:/b.mid"]
