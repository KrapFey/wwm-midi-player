"""Viewer widget."""


from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QStackedLayout, QVBoxLayout, QWidget

from ui.song_delegate import SongDelegate
from utils.common import (
    SPACING_SM,
    Colors,
    active_skin,
    panel_background_qss,
    scrollbar_qss,
    theme_bus,
)

EMPTY_ICON_POINT_SIZE: int = 32


class Viewer(QFrame):
    """Viewer widget.."""

    def __init__(self, accent: Colors=Colors.ACCENT_1, parent: QWidget|None=None) -> None:
        """Initialize Viewer.

        Args:
            accent: The accent color used for the now-playing glyph and
                selection bar.
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.__widget: QListWidget = QListWidget(self)
        self.__delegate: SongDelegate = SongDelegate(self.__widget, accent, self.__widget)
        self.__widget.setItemDelegate(self.__delegate)
        self.__empty_state: QWidget = self.__construct_empty_state()
        self.__stack: QStackedLayout = QStackedLayout()
        self.__stack.addWidget(self.__empty_state)
        self.__stack.addWidget(self.__widget)
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.__stack)
        model = self.__widget.model()
        model.rowsInserted.connect(self.__update_empty_state)
        model.rowsRemoved.connect(self.__update_empty_state)
        # QListWidget.clear() resets the model wholesale rather than emitting
        # per-row rowsRemoved, so modelReset needs its own connection too.
        model.modelReset.connect(self.__update_empty_state)
        self.__update_empty_state()
        self.set_style()
        theme_bus.changed.connect(self.set_style)

    def __construct_empty_state(self) -> QWidget:
        """Build the "no songs loaded" placeholder shown when the playlist is empty.

        Returns:
            The constructed empty-state widget.
        """
        container: QWidget = QWidget()
        layout: QVBoxLayout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACING_SM)
        self.__empty_icon: QLabel = QLabel("♫")
        self.__empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.__empty_hint: QLabel = QLabel("No songs yet — File → Open MIDI file to add some.")
        self.__empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.__empty_icon)
        layout.addWidget(self.__empty_hint)
        return container

    def __update_empty_state(self) -> None:
        """Show the empty-state page when the playlist has no songs, the list otherwise."""
        self.__stack.setCurrentIndex(0 if self.__widget.count() == 0 else 1)

    @property
    def widget(self) -> QListWidget:
        """Return widget.

        Returns:
            The underlying list widget.
        """
        return self.__widget

    def set_now_playing_row(self, row: int) -> None:
        """Mark row as the now-playing track (or -1 for none).

        Args:
            row: The now-playing row index, or -1 if nothing is playing.
        """
        self.__delegate.set_now_playing_row(row)

    def set_style(self) -> None:
        """Apply the panel background and border."""
        # Scoped to Viewer itself: a bare QFrame selector would also box every
        # child QLabel (QLabel is a QFrame), visible whenever BORDER contrasts.
        self.setStyleSheet(f"""
            Viewer {{
                {panel_background_qss()}
                border-radius: {active_skin().radius_md}px;
                border: 1px solid {Colors.BORDER.value.hex};
            }}
        """)
        self.__widget.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent;
                border: none;
                outline: 0;
            }}
            {scrollbar_qss()}
        """)
        self.__empty_icon.setStyleSheet(
            f"color: {Colors.TEXT_MUTED.value.hex}; background: transparent; "
            f"font-size: {EMPTY_ICON_POINT_SIZE}px;")
        self.__empty_hint.setStyleSheet(
            f"color: {Colors.TEXT_MUTED.value.hex}; background: transparent;")

if __name__ == "__main__":
    ...
