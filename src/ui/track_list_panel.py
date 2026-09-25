"""Per-track mute/solo panel: one row per playable track."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.toggle_switch import ToggleSwitch
from utils.common import (
    SPACING_SM,
    Colors,
    active_skin,
    note_color_hex,
    panel_background_qss,
    scrollbar_qss,
    theme_bus,
)
from utils.note_events import TrackSummary

SWATCH_SIZE: int = 12
SOLO_BUTTON_SIZE: int = 22


class _TrackRow(QWidget):
    """One track row: color swatch, name label, solo button, mute ToggleSwitch."""

    toggled: Signal = Signal(int, bool)
    solo_toggled: Signal = Signal(int, bool)

    def __init__(self, track: TrackSummary, parent: QWidget|None=None) -> None:
        """Initialize a row for one track, defaulting to unmuted/not-soloed.

        Args:
            track: The track this row represents.
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.__index: int = track.index
        self.__is_drum: bool = track.is_drum
        self.__swatch: QLabel = QLabel()
        self.__swatch.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
        self.__name_label: QLabel = QLabel(track.name)
        self.__solo_button: QPushButton = QPushButton("S")
        self.__solo_button.setCheckable(True)
        self.__solo_button.setFixedSize(SOLO_BUTTON_SIZE, SOLO_BUTTON_SIZE)
        self.__solo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.__solo_button.setToolTip("Solo: mute every other track")
        self.__style()
        theme_bus.changed.connect(self.__style)
        # clicked (not toggled) fires only on user interaction, not on the
        # programmatic set_soloed()/set_muted() below - so we never need to
        # block signals to push panel-driven state back into a row.
        self.__solo_button.clicked.connect(
            lambda: self.solo_toggled.emit(self.__index, self.__solo_button.isChecked()))
        self.__switch: ToggleSwitch = ToggleSwitch(accent=Colors.VOLUME)
        self.__switch.setChecked(True)
        self.__switch.clicked.connect(
            lambda: self.toggled.emit(self.__index, self.__switch.isChecked()))
        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_SM, SPACING_SM // 2, SPACING_SM, SPACING_SM // 2)
        layout.addWidget(self.__swatch)
        layout.addWidget(self.__name_label, stretch=1)
        layout.addWidget(self.__solo_button)
        layout.addWidget(self.__switch)

    def __style(self) -> None:
        """Apply skin-dependent colors to the swatch, name label, and solo button."""
        self.__swatch.setStyleSheet(
            f"background-color: {note_color_hex(self.__index, self.__is_drum)}; "
            f"border-radius: {SWATCH_SIZE // 2}px;")
        self.__name_label.setStyleSheet(
            f"color: {Colors.WHITE.value.hex}; background: transparent;")
        self.__solo_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BACKGROUND_2.value.hex};
                color: {Colors.TEXT_MUTED.value.hex};
                border: none;
                border-radius: {SOLO_BUTTON_SIZE // 2}px;
                font-weight: bold;
            }}
            QPushButton:checked {{
                background-color: {Colors.SOLO.value.hex};
                color: {Colors.BACKGROUND.value.hex};
            }}
        """)

    def set_muted(self, muted: bool) -> None:
        """Reflect external mute state (e.g. from a solo elsewhere) without emitting toggled.

        Args:
            muted: Whether the row's track should show as muted.
        """
        self.__switch.setChecked(not muted)

    def set_soloed(self, soloed: bool) -> None:
        """Reflect which row (if any) is currently soloed, without emitting solo_toggled.

        Args:
            soloed: Whether this row's track should show as soloed.
        """
        self.__solo_button.setChecked(soloed)


class TrackListPanel(QFrame):
    """Track mute/solo panel, styled like Viewer: one row per playable track of the current song."""

    track_toggled: Signal = Signal(int, bool)
    track_soloed: Signal = Signal(int, bool)

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize TrackListPanel.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.__rows: dict[int, _TrackRow] = {}
        self.__widget: QListWidget = QListWidget(self)
        self.__widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.__widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__widget)
        self.__set_style()
        theme_bus.changed.connect(self.__set_style)

    def load_tracks(self, tracks: list[TrackSummary]) -> None:
        """Clear and rebuild one row per track, in ascending track-index order.

        Args:
            tracks: The tracks to display, one row each.
        """
        self.clear()
        for track in tracks:
            row: _TrackRow = _TrackRow(track)
            row.toggled.connect(self.track_toggled)
            row.solo_toggled.connect(self.track_soloed)
            self.__rows[track.index] = row
            item: QListWidgetItem = QListWidgetItem(self.__widget)
            item.setSizeHint(row.sizeHint())
            self.__widget.addItem(item)
            self.__widget.setItemWidget(item, row)

    def set_muted_tracks(self, tracks: set[int]) -> None:
        """Sync every row's mute switch to the given muted-track set.

        Args:
            tracks: The indices of tracks that should show as muted.
        """
        for index, row in self.__rows.items():
            row.set_muted(index in tracks)

    def set_soloed_track(self, track: int|None) -> None:
        """Sync every row's solo button so only track (if any) shows as soloed.

        Args:
            track: The index of the currently soloed track, or None if no
                track is soloed.
        """
        for index, row in self.__rows.items():
            row.set_soloed(index == track)

    def clear(self) -> None:
        """Remove all rows (song changed, playback errored, or playlist cleared)."""
        self.__rows.clear()
        self.__widget.clear()

    def __set_style(self) -> None:
        """Apply the same panel chrome as Viewer for visual consistency."""
        # Scoped to TrackListPanel itself: a bare QFrame selector would also box every
        # child QLabel (QLabel is a QFrame), visible whenever BORDER contrasts.
        self.setStyleSheet(f"""
            TrackListPanel {{
                {panel_background_qss()}
                border-radius: {active_skin().radius_md}px;
                border: 1px solid {Colors.BORDER.value.hex};
            }}
        """)
        self.__widget.setStyleSheet(f"""
            QListWidget {{ background-color: transparent; border: none; outline: 0; }}
            {scrollbar_qss()}
        """)

if __name__ == "__main__":
    ...
