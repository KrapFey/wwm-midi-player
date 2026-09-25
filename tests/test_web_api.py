"""Tests for the web front end's JS-callable backend (web.api.Api), without a browser."""

import time
from collections.abc import Callable
from pathlib import Path

import mido
import pytest

from utils.app_settings import AppSettings, load_settings, save_settings
from web.api import Api

STEP_TICKS = 48  # 50ms at the default 120 BPM


class FakeSynth:
    def __init__(self) -> None:
        self.notes: list[int] = []
        self.stopped = False

    def noteon(self, _channel: int, note: int, _velocity: int) -> None:
        self.notes.append(note)

    def noteoff(self, _channel: int, _note: int) -> None: ...
    def control_change(self, _channel: int, _control: int, _value: int) -> None: ...
    def program_change(self, _channel: int, _program: int, is_drums: bool = False) -> None: ...

    def stop(self) -> None:
        self.stopped = True


class FakeShell:
    def __init__(self) -> None:
        self.picked: list[str] = []
        self.playlist_to_open: str|None = None
        self.playlist_to_save: str|None = None
        self.revealed: list[str] = []
        self.mini_open = False
        self.main_shown = 0

    def pick_midi_files(self) -> list[str]:
        return list(self.picked)

    def pick_playlist_to_open(self) -> str|None:
        return self.playlist_to_open

    def pick_playlist_to_save(self) -> str|None:
        return self.playlist_to_save

    def reveal(self, path: str) -> None:
        self.revealed.append(path)

    def toggle_mini_player(self) -> None:
        self.mini_open = not self.mini_open

    def mini_player_open(self) -> bool:
        return self.mini_open

    def show_main_window(self) -> None:
        self.main_shown += 1


class FakeKeyManager:
    DEFAULTS = {"low": {"1": "Z", "#1": "Shift+Z", "2": "X"},
                "med": {"1": "A", "#1": "Shift+A", "2": "S"}}

    def __init__(self) -> None:
        self.reset_keybindings()

    @property
    def default_bindings(self) -> dict:
        return self.DEFAULTS

    def update_keybinding(self, octave: str, note: str, key: str) -> None:
        self.bindings[octave][note] = key
        if f"#{note}" in self.bindings[octave]:
            self.bindings[octave][f"#{note}"] = f"Shift+{key}"

    def reset_keybindings(self) -> None:
        self.bindings = {octave: dict(notes) for octave, notes in self.DEFAULTS.items()}


def _song(path: Path, tracks: list[list[int]]) -> str:
    midi = mido.MidiFile(ticks_per_beat=480)
    for index, notes in enumerate(tracks):
        track = mido.MidiTrack()
        for note in notes:
            track.append(mido.Message("note_on", channel=index, note=note, velocity=90, time=0))
            track.append(mido.Message("note_off", channel=index, note=note, velocity=0,
                                      time=STEP_TICKS))
        midi.tracks.append(track)
    midi.save(path)
    return str(path)


def _wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.fixture
def harness(tmp_path: Path):
    events: list[tuple[str, object]] = []
    shell = FakeShell()
    synth = FakeSynth()
    settings = tmp_path / "settings.json"
    save_settings(AppSettings(is_audio_mode=True), settings)
    keys = FakeKeyManager()
    api = Api(emit=lambda name, payload: events.append((name, payload)), shell=shell,
              settings_path=settings, soundfont=tmp_path / "unused.sf2",
              synth_factory=lambda _path: synth, key_manager=lambda: keys)
    api.shell = shell  # test-only handle
    yield api, events, shell.picked, synth, tmp_path
    api.close()


def _names(events: list[tuple[str, object]]) -> list[str]:
    return [name for name, _ in events]


def test_restores_saved_settings_and_drops_missing_files(tmp_path: Path) -> None:
    existing = _song(tmp_path / "a.mid", [[60]])
    settings = tmp_path / "settings.json"
    save_settings(AppSettings(volume=42, is_audio_mode=True, skin="cyberpunk", theme="light",
                              playlist=[existing, str(tmp_path / "gone.mid")], current_index=0),
                  settings)
    state = Api(lambda *_: None, FakeShell(), settings_path=settings).get_state()
    assert (state["volume"], state["is_audio"], state["skin"], state["theme"]) == \
        (42, True, "cyberpunk", "light")
    assert [f["path"] for f in state["files"]] == [existing]
    assert state["current"] == 0


def test_unknown_saved_skin_and_theme_fall_back(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    save_settings(AppSettings(skin="nope", theme="neon"), settings)
    state = Api(lambda *_: None, FakeShell(), settings_path=settings).get_state()
    assert (state["skin"], state["theme"]) == ("default", "dark")


def test_add_files_appends_and_selects_first(harness) -> None:
    api, _, picked, _, tmp_path = harness
    picked.append(_song(tmp_path / "Artist - Title.mid", [[60]]))
    state = api.add_files()
    assert state["current"] == 0
    assert state["files"][0]["title"] == "Title"
    assert state["files"][0]["artist"] == "Artist"


def test_play_runs_to_end_then_goes_idle(harness) -> None:
    api, events, picked, synth, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60, 62]]))
    api.add_files()
    api.play_index(0)
    _wait_for(lambda: api.get_state()["now_playing"] == -1 and not api.get_state()["playing"])
    assert synth.notes == [60, 62]
    assert {"duration", "notes", "tracks", "clock"} <= set(_names(events))


def test_song_end_auto_advances(harness) -> None:
    api, _, picked, synth, tmp_path = harness
    picked.extend([_song(tmp_path / "a.mid", [[60]]), _song(tmp_path / "b.mid", [[72]])])
    api.add_files()
    api.play_index(0)
    _wait_for(lambda: synth.notes == [60, 72])
    _wait_for(lambda: api.get_state()["now_playing"] == -1)
    assert api.get_state()["current"] == 1


def test_solo_mutes_every_other_loaded_track_and_manual_change_clears_it(harness) -> None:
    api, events, picked, _, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60] * 20, [72] * 20]))
    api.add_files()
    api.play_index(0)
    _wait_for(lambda: "tracks" in _names(events))
    assert api.solo_track(1, soloed=True) == {"muted": [0], "soloed": 1}
    assert api.set_track_enabled(0, enabled=True) == {"muted": [], "soloed": None}


def test_seek_keeps_mute_state_but_new_song_clears_it(harness) -> None:
    api, events, picked, _, tmp_path = harness
    picked.extend([_song(tmp_path / "a.mid", [[60] * 20, [72] * 20]),
                   _song(tmp_path / "b.mid", [[60] * 20])])
    api.add_files()
    api.play_index(0)
    _wait_for(lambda: "tracks" in _names(events))
    api.set_track_enabled(1, enabled=False)
    api.seek(0.2)
    assert api.get_state()["muted"] == [1]
    api.play_index(1)
    assert api.get_state()["muted"] == []


def test_error_reports_message_and_resets_clock(harness) -> None:
    api, events, picked, _, tmp_path = harness
    broken = tmp_path / "broken.mid"
    broken.write_bytes(b"not a midi file")
    picked.append(str(broken))
    api.add_files()
    api.play_index(0)
    _wait_for(lambda: "error" in _names(events))
    _wait_for(lambda: not api.get_state()["playing"])
    assert api.get_clock() == {"position": 0.0, "playing": False}


def test_clear_playlist_stops_and_empties(harness) -> None:
    api, _, picked, _, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60] * 40]))
    api.add_files()
    api.play_index(0)
    state = api.clear_playlist()
    assert state["files"] == []
    assert state["current"] == -1
    assert not state["playing"]


def test_close_saves_settings_and_stops_synth(harness) -> None:
    api, _, picked, synth, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60]]))
    api.add_files()
    api.set_volume(33)
    api.set_skin("cyberpunk")
    api.play_index(0)
    api.close()
    saved = load_settings(tmp_path / "settings.json")
    assert (saved.volume, saved.skin, saved.playlist) == (33, "cyberpunk", picked)
    assert synth.stopped


def test_piano_layout_covers_88_keys_normalized() -> None:
    layout = Api.get_piano_layout()
    assert len(layout) == 88
    assert all(0.0 <= x <= 1.0 and 0.0 < width < 1.0 for _, x, width, _ in layout)
    assert sum(1 for *_, white in layout if white) == 52


def test_add_paths_expands_folders_and_ignores_other_files(harness) -> None:
    api, _, _, _, tmp_path = harness
    (tmp_path / "album").mkdir()
    _song(tmp_path / "album" / "b.mid", [[60]])
    _song(tmp_path / "album" / "a.mid", [[60]])
    (tmp_path / "notes.txt").write_text("x")
    state = api.add_paths([str(tmp_path / "album"), str(tmp_path / "notes.txt")])
    assert [Path(f["path"]).name for f in state["files"]] == ["a.mid", "b.mid"]


def test_details_arrive_in_background(harness) -> None:
    api, events, picked, _, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60, 100], [62]]))
    api.add_files()
    _wait_for(lambda: "details" in _names(events))
    entry = api.get_state()["files"][0]
    assert (entry["tracks"], entry["in_range"]) == (2, 2 / 3)
    assert entry["duration"] > 0


def test_remove_now_playing_song_stops_and_keeps_selection_in_bounds(harness) -> None:
    api, _, picked, _, tmp_path = harness
    picked.extend([_song(tmp_path / f"{n}.mid", [[60] * 40]) for n in "abc"])
    api.add_files()
    api.play_index(2)
    state = api.remove_file(2)
    assert not state["playing"]
    assert (state["now_playing"], state["current"], len(state["files"])) == (-1, 1, 2)


def test_remove_earlier_song_shifts_now_playing(harness) -> None:
    api, _, picked, _, tmp_path = harness
    picked.extend([_song(tmp_path / f"{n}.mid", [[60] * 40]) for n in "abc"])
    api.add_files()
    api.play_index(2)
    state = api.remove_file(0)
    assert (state["now_playing"], state["current"]) == (1, 1)
    assert state["playing"]


def test_move_file_reorders_and_selection_follows(harness) -> None:
    api, _, picked, _, tmp_path = harness
    picked.extend([_song(tmp_path / f"{n}.mid", [[60]]) for n in "abc"])
    api.add_files()
    state = api.move_file(0, 2)
    assert [Path(f["path"]).stem for f in state["files"]] == ["b", "c", "a"]
    assert state["current"] == 2


def test_save_and_load_playlist_skips_missing_files(harness) -> None:
    api, events, picked, _, tmp_path = harness
    picked.extend([_song(tmp_path / "a.mid", [[60]]), _song(tmp_path / "b.mid", [[60]])])
    api.add_files()
    api.shell.playlist_to_save = str(tmp_path / "list.m3u")
    assert api.save_playlist()
    Path(picked[1]).unlink()
    api.clear_playlist()
    api.shell.playlist_to_open = str(tmp_path / "list.m3u")
    state = api.load_playlist()
    assert [f["path"] for f in state["files"]] == [picked[0]]
    assert "status" in _names(events)


def test_transpose_is_clamped_remembered_and_saved(harness) -> None:
    api, _, picked, synth, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60]]))
    api.add_files()
    assert api.set_transpose(99)["files"][0]["transpose"] == 24
    api.set_transpose(-12)
    api.play_index(0)
    _wait_for(lambda: synth.notes == [48])
    api.close()
    assert load_settings(tmp_path / "settings.json").transpose == {picked[0]: -12}


def test_auto_transpose_fits_song_into_wwm_range(harness) -> None:
    api, _, picked, _, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[96, 100]]))
    api.add_files()
    entry = api.auto_transpose()["files"][0]
    assert entry["transpose"] == -17
    assert entry["in_range"] == 1.0


def test_set_keybinding_rejects_bad_keys_and_duplicates(harness) -> None:
    api, *_ = harness
    assert not api.set_keybinding("low", "1", "!")["ok"]
    assert not api.set_keybinding("low", "#1", "Q")["ok"]
    taken = api.set_keybinding("low", "1", "a")
    assert not taken["ok"] and "Med 1" in taken["error"]
    result = api.set_keybinding("low", "1", "q")
    assert result["ok"]
    assert result["bindings"]["low"]["1"] == "Q"
    assert result["bindings"]["low"]["#1"] == "Shift+Q"
    assert api.reset_keybindings()["bindings"]["low"]["1"] == "Z"


def test_reveal_and_mini_player_go_through_shell(harness) -> None:
    api, _, picked, _, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60]]))
    api.add_files()
    api.reveal_file(0)
    assert api.shell.revealed == picked
    assert api.toggle_mini_player()["mini_open"]
    assert not api.toggle_mini_player()["mini_open"]
    api.toggle_mini_player()
    api.show_main_window()
    assert (api.shell.mini_open, api.shell.main_shown) == (False, 1)


def test_seek_while_paused_stays_paused_at_the_new_position(harness) -> None:
    api, events, picked, synth, tmp_path = harness
    picked.append(_song(tmp_path / "a.mid", [[60] * 60]))
    api.add_files()
    api.play_index(0)
    _wait_for(lambda: "duration" in _names(events))
    api.play_pause()
    heard = len(synth.notes)
    api.seek(1.0)
    _wait_for(lambda: api.get_clock()["position"] == 1.0)
    time.sleep(0.3)
    assert api.get_clock() == {"position": 1.0, "playing": False}
    assert api.get_state()["paused"]
    assert len(synth.notes) == heard  # nothing sounds while paused
    clocks = [payload for name, payload in events if name == "clock"]
    assert clocks[-1] == {"position": 1.0, "playing": False}  # page told it's paused
