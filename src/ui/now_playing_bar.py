"""Persistent bottom-docked Now Playing bar: track info, transport, progress, volume."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.buttons.next import NextButton
from ui.buttons.play import PlayButton
from ui.buttons.previous import PreviousButton
from ui.buttons.repeat import RepeatButton
from ui.buttons.shuffle import ShuffleButton
from ui.glow import set_widget_glow
from ui.progressbar import ProgressBar
from ui.toggle_switch import ToggleSwitch
from ui.volume_slider import Volume
from utils.common import (
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
    Colors,
    active_skin,
    heading_font_qss,
    mono_font_qss,
    panel_background_qss,
    theme_bus,
)
from utils.skins import Skin

# Fixed width shared by both the title/artist column and the volume/mode
# column: long track/artist names elide instead of growing the left side,
# and matching widths on both sides keep the transport/progress area
# centered on the window rather than just centered within the leftover gap.
SIDE_COLUMN_WIDTH: int = 220
# HUD skins: tiny status indicator chips under the track title.
STATUS_CHIP_HEIGHT: int = 18


class NowPlayingBar(QFrame):
    """Bottom-docked bar: track info (left), transport+progress (center), volume/mode (right)."""

    seek_requested: Signal = Signal(int)

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize NowPlayingBar.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        # (label, original text): HUD skins show captions uppercased.
        self.__caption_labels: list[tuple[QLabel, str]] = []
        self.__is_playing: bool = False
        self.__status_chip: QLabel = QLabel()
        self.__mode_chip: QLabel = QLabel()
        self.__status_row: QWidget = self.__construct_status_row()
        self.__title_label: QLabel = QLabel("No files loaded")
        self.__title_label.setFixedWidth(SIDE_COLUMN_WIDTH)
        self.__artist_label: QLabel = QLabel("")
        self.__artist_label.setFixedWidth(SIDE_COLUMN_WIDTH)
        self.__artist_label.setVisible(False)
        self.__progressbar: ProgressBar = ProgressBar()
        self.__current_seconds: int = 0
        self.__duration_seconds: int = 0
        self.__time_label: QLabel = QLabel("00:00 / 00:00")
        self.__shuffle_button: ShuffleButton = ShuffleButton()
        self.__previous_button: PreviousButton = PreviousButton()
        self.__play_button: PlayButton = PlayButton()
        self.__next_button: NextButton = NextButton()
        self.__repeat_button: RepeatButton = RepeatButton()
        self.__previous_button.setToolTip("Previous (F9)")
        self.__play_button.setToolTip("Play (F10)")
        self.__next_button.setToolTip("Next (F11)")
        self.__mode_toggle: ToggleSwitch = ToggleSwitch(accent=Colors.MODE)
        self.__volume: Volume = Volume()
        self.__construct_layout()
        self.__progressbar.seek_requested.connect(self.seek_requested)
        self.__play_button.change.connect(self.__on_play_state_changed)
        self.__mode_toggle.toggled.connect(self.__style_status_chips)
        self.set_style()
        self.__style_labels()
        self.__style_status_chips()
        theme_bus.changed.connect(self.set_style)
        theme_bus.changed.connect(self.__style_labels)
        theme_bus.changed.connect(self.__style_status_chips)

    @property
    def play_button(self) -> PlayButton:
        """Return the play/pause button.

        Returns:
            The play/pause button.
        """
        return self.__play_button

    @property
    def previous_button(self) -> PreviousButton:
        """Return the previous-track button.

        Returns:
            The previous-track button.
        """
        return self.__previous_button

    @property
    def next_button(self) -> NextButton:
        """Return the next-track button.

        Returns:
            The next-track button.
        """
        return self.__next_button

    @property
    def repeat_button(self) -> RepeatButton:
        """Return the repeat toggle button.

        Returns:
            The repeat toggle button.
        """
        return self.__repeat_button

    @property
    def shuffle_button(self) -> ShuffleButton:
        """Return the shuffle toggle button.

        Returns:
            The shuffle toggle button.
        """
        return self.__shuffle_button

    @property
    def mode_toggle(self) -> ToggleSwitch:
        """Return the Audio/WWM mode toggle.

        Returns:
            The Audio/WWM mode toggle switch.
        """
        return self.__mode_toggle

    @property
    def volume(self) -> Volume:
        """Return the volume slider.

        Returns:
            The volume slider widget.
        """
        return self.__volume

    @staticmethod
    def __convert_to_mm_ss(seconds: int) -> tuple[int, int]:
        """Convert seconds to humane format MM:SS.

        Args:
            seconds: Total seconds to convert.

        Returns:
            A (minutes, seconds) tuple.
        """
        return divmod(seconds, 60)

    @staticmethod
    def __set_elided_text(label: QLabel, text: str) -> None:
        """Set label's text elided to its fixed width, with the full text as a tooltip.

        Args:
            label: The label to update.
            text: The full, unelided text.
        """
        metrics: QFontMetrics = QFontMetrics(label.font())
        label.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, SIDE_COLUMN_WIDTH))
        label.setToolTip(text)

    def set_header(self, title: str, artist: str="") -> None:
        """Set the now-playing header text, eliding long titles/artists.

        Args:
            title: The track title to display.
            artist: The track artist to display; hidden entirely if empty.
        """
        self.__set_elided_text(self.__title_label, title)
        self.__set_elided_text(self.__artist_label, artist)
        self.__artist_label.setVisible(bool(artist))

    def set_duration(self, seconds: int) -> None:
        """Set the track duration: progress bar max and the combined time label.

        Args:
            seconds: The track's total duration in seconds.
        """
        self.__duration_seconds = seconds
        self.__progressbar.setMaximum(seconds)
        self.__update_time_label()

    def set_current_time(self, seconds: int) -> None:
        """Set the current playback position: progress bar value and the combined time label.

        Args:
            seconds: The current playback position in seconds.
        """
        self.__current_seconds = seconds
        self.__progressbar.setValue(seconds)
        self.__update_time_label()

    def reset_progress(self) -> None:
        """Reset the progress bar and time label to zero."""
        self.__current_seconds = 0
        self.__duration_seconds = 0
        self.__progressbar.setValue(0)
        self.__update_time_label()

    def __update_time_label(self) -> None:
        """Refresh the combined "current / duration" time label."""
        current_minutes, current_secs = self.__convert_to_mm_ss(self.__current_seconds)
        duration_minutes, duration_secs = self.__convert_to_mm_ss(self.__duration_seconds)
        self.__time_label.setText(
            f"{current_minutes}:{current_secs:02d} / {duration_minutes}:{duration_secs:02d}")

    def __construct_header(self) -> QVBoxLayout:
        """Construct the track-info column.

        Returns:
            The assembled track-info column layout.
        """
        layout: QVBoxLayout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.__title_label)
        layout.addWidget(self.__artist_label)
        layout.addWidget(self.__status_row)
        layout.addStretch()
        return layout

    def __construct_status_row(self) -> QWidget:
        """Construct the HUD status chips row (playback state, Audio/WWM mode).

        Returns:
            The status row container; shown only on HUD skins.
        """
        row: QWidget = QWidget()
        row.setStyleSheet("background: transparent;")
        layout: QHBoxLayout = QHBoxLayout(row)
        layout.setContentsMargins(0, SPACING_XS, 0, 0)
        layout.setSpacing(SPACING_XS)
        for chip in (self.__status_chip, self.__mode_chip):
            chip.setFixedHeight(STATUS_CHIP_HEIGHT)
            layout.addWidget(chip)
        layout.addStretch()
        return row

    def __on_play_state_changed(self, is_playing: bool) -> None:
        """Track playing/paused state for the HUD status chip.

        Args:
            is_playing: True while a track is playing, False when paused/stopped.
        """
        self.__is_playing = is_playing
        self.__style_status_chips()

    @staticmethod
    def __style_chip(chip: QLabel, text: str, color: Colors) -> None:
        """Style one glowing HUD status chip.

        Args:
            chip: The chip label to style.
            text: The chip's text.
            color: The chip's category color (text, border, and glow).
        """
        chip.setText(text)
        chip.setStyleSheet(
            f"color: {color.value.hex}; border: 1px solid {color.value.hex}; "
            f"border-radius: {STATUS_CHIP_HEIGHT // 2}px; padding: 0px 8px; font-size: 10px; "
            f"font-weight: bold; background: transparent; {mono_font_qss()}")
        set_widget_glow(chip, color.value.qcolor)

    def __style_status_chips(self) -> None:
        """Refresh the HUD status chips, showing them only on HUD skins."""
        visible: bool = active_skin().hud
        self.__status_row.setVisible(visible)
        if not visible:
            return
        if self.__is_playing:
            self.__style_chip(self.__status_chip, "\u25cf PLAYING", Colors.GREEN)
        else:
            self.__style_chip(self.__status_chip, "\u25cf STANDBY", Colors.TEXT_MUTED)
        mode: str = "AUDIO" if self.__mode_toggle.isChecked() else "WWM"
        self.__style_chip(self.__mode_chip, mode, Colors.MODE)

    def __construct_transport_row(self) -> QHBoxLayout:
        """Construct the centered transport buttons row.

        Returns:
            The assembled transport buttons row layout.
        """
        layout: QHBoxLayout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(self.__shuffle_button)
        layout.addWidget(self.__previous_button)
        layout.addWidget(self.__play_button)
        layout.addWidget(self.__next_button)
        layout.addWidget(self.__repeat_button)
        layout.addStretch()
        return layout

    def __construct_progress_row(self) -> QHBoxLayout:
        """Construct the progress bar + combined time label row.

        Returns:
            The assembled progress row layout.
        """
        layout: QHBoxLayout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)
        layout.addWidget(self.__progressbar, stretch=1)
        layout.addWidget(self.__time_label)
        return layout

    def __construct_center_column(self) -> QVBoxLayout:
        """Construct the transport+progress center column.

        Returns:
            The assembled center column layout.
        """
        layout: QVBoxLayout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)
        layout.addLayout(self.__construct_transport_row())
        layout.addLayout(self.__construct_progress_row())
        return layout

    def __make_caption_label(self, text: str) -> QLabel:
        """Construct a small caption label with readable contrast on the dark panel.

        Args:
            text: The caption text to display.

        Returns:
            The constructed caption label.
        """
        label: QLabel = QLabel(text)
        self.__caption_labels.append((label, text))
        return label

    def __construct_right_column(self) -> QWidget:
        """Construct the volume + mode-toggle column, right-aligned in a fixed-width slot.

        Wrapped in a SIDE_COLUMN_WIDTH-wide container (rather than added as a
        bare layout) so it matches the header column's width; a leading
        stretch keeps the actual controls flush against the window's right
        edge - same as before - instead of letting them get pulled toward
        center or, worse, stretched to fill the extra width themselves
        (which would visibly distort the fixed-size mode toggle).

        Returns:
            The container widget for the volume/mode-toggle column.
        """
        content: QVBoxLayout = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        volume_row: QHBoxLayout = QHBoxLayout()
        volume_row.addWidget(self.__make_caption_label("Volume"))
        volume_row.addWidget(self.__volume)
        mode_row: QHBoxLayout = QHBoxLayout()
        mode_row.addWidget(self.__make_caption_label("WWM"))
        mode_row.addWidget(self.__mode_toggle, stretch=1)
        mode_row.addWidget(self.__make_caption_label("Audio"))
        content.addLayout(volume_row)
        content.addLayout(mode_row)
        outer: QHBoxLayout = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()
        outer.addLayout(content)
        container: QWidget = QWidget()
        container.setLayout(outer)
        container.setFixedWidth(SIDE_COLUMN_WIDTH)
        # Qt's default style can paint a plain QWidget's background using a
        # native palette role rather than leaving it transparent - explicit
        # here so it doesn't show a seam against the parent frame's own fill.
        container.setStyleSheet("background: transparent;")
        return container

    def __construct_layout(self) -> None:
        """Construct NowPlayingBar layout."""
        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD)
        layout.setSpacing(SPACING_MD)
        layout.addLayout(self.__construct_header())
        layout.addLayout(self.__construct_center_column(), stretch=1)
        layout.addWidget(self.__construct_right_column())

    def set_style(self) -> None:
        """Apply the panel background and top divider."""
        divider: Colors = Colors.BORDER if active_skin().glass else Colors.BACKGROUND_2
        self.setStyleSheet(f"""
            NowPlayingBar {{
                {panel_background_qss()}
                border-top: 1px solid {divider.value.hex};
            }}
        """)

    def __style_labels(self) -> None:
        """(Re)apply skin-dependent colors/fonts to every plain-text label in the bar.

        Neon skins give the title and time readout a soft glow; HUD skins set
        the time in the monospaced instrument face and turn the captions into
        small uppercase technical labels.
        """
        skin: Skin = active_skin()
        self.__title_label.setStyleSheet(
            f"font-weight: bold; font-size: 16px; background: transparent; "
            f"color: {Colors.WHITE.value.hex}; {heading_font_qss()}")
        self.__artist_label.setStyleSheet(
            f"color: {Colors.TEXT_MUTED.value.hex}; font-size: 12px; background: transparent;")
        self.__time_label.setStyleSheet(
            f"font-weight: bold; background: transparent; color: {Colors.WHITE.value.hex}; "
            f"{mono_font_qss()}")
        glow: bool = skin.neon_glow
        set_widget_glow(self.__title_label, Colors.ACCENT_1.value.qcolor if glow else None)
        set_widget_glow(self.__time_label, Colors.HIGHLIGHT.value.qcolor if glow else None)
        for label, text in self.__caption_labels:
            if skin.hud:
                label.setText(text.upper())
                label.setStyleSheet(
                    f"color: {Colors.TEXT_MUTED.value.hex}; background: transparent; "
                    f"font-size: 10px; font-weight: bold; {mono_font_qss()}")
            else:
                label.setText(text)
                label.setStyleSheet(f"color: {Colors.WHITE.value.hex}; background: transparent;")

if __name__ == "__main__":
    ...
