"""WWM MIDI Player - app entry point.

Runs the Python backend (utils/*, via web.api.Api) behind an HTML/CSS/JS
interface rendered by the system WebView2 through pywebview.
"""

import ctypes
import json
import os
import subprocess

import keyboard
import webview
from webview.dom import DOMEventHandler

from utils.resources import resource_path
from web.api import Api

WINDOW_TITLE: str = "WWM MIDI Player"
# Windows taskbar identity. Without an explicit one, a run from source is
# grouped under python.exe and the taskbar shows Python's icon, not ours.
APP_USER_MODEL_ID: str = "KrapFey.WWMMidiPlayer"
ICON: str = str(resource_path("src/input/logo.ico").resolve())
MIDI_FILE_TYPES: tuple[str, ...] = ("MIDI Files (*.mid;*.midi)",)
PLAYLIST_FILE_TYPES: tuple[str, ...] = ("Playlists (*.m3u)",)
# Relative to this script's folder (or the PyInstaller bundle root): pywebview
# serves such local paths over its built-in HTTP server, which ES modules need
# (browsers refuse to load module scripts from file:// URLs).
INDEX_PAGE: str = "web/static/index.html"
MINI_PAGE: str = "web/static/mini.html"
MINI_SIZE: tuple[int, int] = (440, 136)
BACKGROUND: str = "#0A0C10"


class Desktop:
    """The pywebview side of the app: windows, native dialogs, and Api's Shell."""

    def __init__(self) -> None:
        """Create the backend and the main window (shown once webview.start() runs)."""
        self.api: Api = Api(self.emit, self)
        self.main: webview.Window = webview.create_window(
            WINDOW_TITLE, INDEX_PAGE, js_api=self.api, width=1400, height=850,
            min_size=(960, 600), background_color=BACKGROUND)
        self.mini: webview.Window|None = None
        self.main.events.loaded += self.__on_main_loaded
        self.main.events.closing += self.__on_main_closing

    def emit(self, event: str, payload: object) -> None:
        """Push a backend event to every open page (a no-op for pages not loaded yet).

        Args:
            event: The event name, dispatched by the page's window.app.onEvent.
            payload: The JSON-serializable event data.
        """
        script: str = (f"window.app && window.app.onEvent({json.dumps(event)}, "
                       f"{json.dumps(payload)})")
        for window in (self.main, self.mini):
            if window is None:
                continue
            try:
                window.evaluate_js(script)
            except Exception:  # noqa: BLE001 - window closing/closed; nothing to update
                continue

    # --- Shell (see web.api.Shell) -----------------------------------------

    def pick_midi_files(self) -> list[str]:
        """Show the native multi-select MIDI file dialog.

        Returns:
            The chosen paths, or [] if cancelled.
        """
        chosen = self.main.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                              file_types=MIDI_FILE_TYPES)
        return list(chosen or [])

    def pick_playlist_to_open(self) -> str|None:
        """Show the native open-playlist dialog.

        Returns:
            The chosen .m3u path, or None if cancelled.
        """
        chosen = self.main.create_file_dialog(webview.FileDialog.OPEN,
                                              file_types=PLAYLIST_FILE_TYPES)
        return chosen[0] if chosen else None

    def pick_playlist_to_save(self) -> str|None:
        """Show the native save-playlist dialog.

        Returns:
            The chosen .m3u path, or None if cancelled.
        """
        chosen = self.main.create_file_dialog(webview.FileDialog.SAVE,
                                              save_filename="playlist.m3u",
                                              file_types=PLAYLIST_FILE_TYPES)
        if isinstance(chosen, (list, tuple)):  # backends differ: str or 1-tuple
            chosen = chosen[0] if chosen else None
        return chosen or None

    def reveal(self, path: str) -> None:
        """Open Explorer with path selected.

        Args:
            path: The file to show.
        """
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])

    def toggle_mini_player(self) -> None:
        """Open the always-on-top mini player, or close it if it's open."""
        if self.mini is not None:
            self.mini.destroy()
            self.mini = None
            return
        self.mini = webview.create_window(
            f"{WINDOW_TITLE} - Mini", MINI_PAGE, js_api=self.api,
            width=MINI_SIZE[0], height=MINI_SIZE[1], resizable=False, on_top=True,
            frameless=True, easy_drag=False, background_color=BACKGROUND)
        self.mini.events.closed += self.__on_mini_closed

    def mini_player_open(self) -> bool:
        """Return whether the mini player is open.

        Returns:
            True if the mini player window exists.
        """
        return self.mini is not None

    def show_main_window(self) -> None:
        """Restore the main window (e.g. from minimized) and bring it forward."""
        self.main.restore()
        self.main.show()

    # --- Window events -----------------------------------------------------

    def __on_main_loaded(self) -> None:
        """Accept files dropped onto the page.

        Browsers never reveal a dropped file's real path to page JS; pywebview
        adds it (pywebviewFullPath) for drops handled by a Python DOM handler.
        """
        self.main.dom.document.events.drop += DOMEventHandler(
            self.__on_drop, prevent_default=True, stop_propagation=True)

    def __on_drop(self, event: dict) -> None:
        """Add dropped MIDI files/folders to the playlist.

        Args:
            event: The DOM drop event, with pywebviewFullPath on each file.
        """
        files: list[dict] = event.get("dataTransfer", {}).get("files", [])
        paths: list[str] = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if paths:
            self.api.add_paths(paths)

    def __on_mini_closed(self) -> None:
        """Forget the mini player when it's closed by any means (e.g. Alt+F4)."""
        self.mini = None
        self.emit("state", self.api.get_state())

    def __on_main_closing(self) -> None:
        """Save settings, stop playback, and take the mini player down with the app."""
        self.api.close()
        if self.mini is not None:
            self.mini.destroy()


def main() -> None:
    """Create the windows, register global hotkeys, and run until the main window closes."""
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    desktop: Desktop = Desktop()
    api: Api = desktop.api

    def notify_state() -> None:
        """Push the full state after a hotkey changed it outside the page."""
        desktop.emit("state", api.get_state())

    def toggle_mode() -> None:
        """Flip between Audio and WWM mode (F8)."""
        api.set_audio_mode(not api.get_state()["is_audio"])

    # Global hotkeys, so the player can be driven while the game has focus.
    # Api is thread-safe, so the keyboard hook thread can call it directly.
    keyboard.add_hotkey("f9", lambda: (api.previous_track(), notify_state()))
    keyboard.add_hotkey("f10", lambda: (api.play_pause(), notify_state()))
    keyboard.add_hotkey("f11", lambda: (api.next_track(), notify_state()))
    keyboard.add_hotkey("f8", toggle_mode)
    # Window/taskbar icon for every window. (pywebview's docstring says GTK/QT
    # only, but its Windows backend honors it too; without it the icon comes
    # from the running executable - python.exe when run from source.)
    webview.start(icon=ICON)


if __name__ == "__main__":
    main()
