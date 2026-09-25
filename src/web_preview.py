"""Serve the web UI to a normal browser with a mock backend, for UI development.

Usage: `python src/web_preview.py [port]`, then open the printed URL. The page
detects that pywebview isn't there and falls back to js/mock.js, which loads
/mock-state.json - a snapshot of the real web.api.Api state (real skins, piano
layout, and default keybindings) plus a demo playlist, tracks, and falling
notes. URL parameters such as ?skin=cyberpunk&theme=light&tab=tracks override
the snapshot (see js/mock.js); open /mini.html for the mini player.
"""

import json
import sys
import tempfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from utils.song_analysis import playable_fraction
from utils.wwm_macro import KeyManager
from web.api import Api

STATIC_ROOT: Path = Path(__file__).parent / "web" / "static"
DEFAULT_PORT: int = 8765
DEMO_FILES: tuple[str, ...] = (
    "Hans Zimmer - Time.mid", "Joe Hisaishi - One Summer's Day.mid",
    "Yiruma - River Flows in You.mid", "Toby Fox - Megalovania.mid",
)
DEMO_TRACKS: tuple[str, ...] = ("Piano RH", "Piano LH", "Strings", "Bass", "Drums")
# (duration seconds, track count, transpose) per demo song.
DEMO_DETAILS: tuple[tuple[float, int, int], ...] = (
    (275.0, 6, 0), (245.0, 5, -5), (198.0, 2, 0), (156.0, 9, 12))


class PreviewShell:
    """Minimal web.api.Shell for building the snapshot: "picks" the demo files."""

    def pick_midi_files(self) -> list[str]:
        """Return the demo playlist."""
        return list(DEMO_FILES)

    def pick_playlist_to_open(self) -> None:
        """Unused in the preview."""

    def pick_playlist_to_save(self) -> None:
        """Unused in the preview."""

    def reveal(self, path: str) -> None:
        """Unused in the preview."""

    def toggle_mini_player(self) -> None:
        """Unused in the preview."""

    def mini_player_open(self) -> bool:
        """The preview never has a mini player open."""
        return False

    def show_main_window(self) -> None:
        """Unused in the preview."""


def build_snapshot() -> dict:
    """Build the mock backend's data from a real Api, with demo content filled in.

    Returns:
        {"state", "layout", "notes", "clock"} for js/mock.js.
    """
    settings: Path = Path(tempfile.mkdtemp()) / "settings.json"
    api: Api = Api(lambda *_: None, PreviewShell(), settings_path=settings)
    api.add_files()
    state: dict = api.get_state()
    state.update(current=1, now_playing=1, playing=True, duration=245.0, is_audio=True,
                 tracks=[{"index": i, "name": name, "is_drum": name == "Drums"}
                         for i, name in enumerate(DEMO_TRACKS)])
    notes: list[list] = sorted(
        ([0.2 + i * 0.09, 0.6 + i * 0.09 + (i % 4) * 0.3, 40 + (i * 7) % 48, i % 5, i % 5 == 4]
         for i in range(60)), key=lambda note: note[0])
    pitches: tuple[int, ...] = tuple(note[2] for note in notes)
    for entry, (duration, tracks, shift) in zip(state["files"], DEMO_DETAILS, strict=True):
        entry.update(duration=duration, tracks=tracks, transpose=shift,
                     in_range=playable_fraction(pitches, shift))
    return {"state": state, "layout": api.get_piano_layout(), "notes": notes,
            "clock": {"position": 1.6, "playing": False},
            "keybindings": KeyManager().default_bindings}


class PreviewHandler(SimpleHTTPRequestHandler):
    """Static file handler that also serves /mock-state.json, never cached."""

    snapshot: bytes = b""

    def end_headers(self) -> None:
        """Disable caching, so edited CSS/JS always shows up on reload."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming convention
        """Serve the mock snapshot, or fall back to static files."""
        if self.path != "/mock-state.json":
            super().do_GET()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.snapshot)))
        self.end_headers()
        self.wfile.write(self.snapshot)


def main() -> None:
    """Serve the preview until interrupted."""
    port: int = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    PreviewHandler.snapshot = json.dumps(build_snapshot()).encode()
    server: ThreadingHTTPServer = ThreadingHTTPServer(
        ("127.0.0.1", port), partial(PreviewHandler, directory=str(STATIC_ROOT)))
    print(f"Web UI preview: http://127.0.0.1:{port}/index.html", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
