"""Simple Toggle switch."""

from typing import override

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractButton, QWidget

from ui.glow import set_widget_glow
from utils.common import Colors, active_skin, theme_bus

DISABLED_OPACITY: float = 0.4


class ToggleSwitch(QAbstractButton):
    """Modern Toggle Switch."""

    __position_changed: Signal = Signal(float)

    def __init__(self, parent: QWidget|None=None, accent: Colors=Colors.ACCENT_1) -> None:
        """Initialize toggle.

        Args:
            parent: Optional parent widget.
            accent: The track color while checked - lets each category of
                toggle carry its own accent (e.g. Colors.MODE).
        """
        super().__init__(parent=parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Caching the shared QColor is safe: skin/theme switches mutate it in
        # place (see utils.common._apply_appearance), so it always reflects
        # the active palette.
        self.__checked_color: QColor = accent.value.qcolor
        self.__knob_color: QColor = QColor("#FFFFFF")
        self.__width: int = 45
        self.__height: int = int(self.__width * .52)
        self.__offset: int = 2
        self.__knob_size: int = self.__height - (self.__offset * 2)
        self.__position: float = self.__offset
        # Fixed, not just minimum: paintEvent's track uses the real widget
        # size while the knob's stop positions are computed from __width/
        # __height, so if a parent layout (e.g. a stretch=1 row) grew this
        # widget wider than that, the two would disagree and the knob would
        # visibly rest short of the track's actual edge.
        self.setFixedSize(self.__width, self.__height)
        self.__animation: QPropertyAnimation = QPropertyAnimation(self, b"position", self)
        self.__animation.setDuration(250)
        self.__animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self.__start_animation)
        self.toggled.connect(self.__sync_glow)
        theme_bus.changed.connect(self.update)
        theme_bus.changed.connect(self.__sync_glow)

    def __sync_glow(self) -> None:
        """Glow in the accent color while checked, on neon-glow skins only."""
        glowing: bool = self.isChecked() and active_skin().neon_glow
        set_widget_glow(self, self.__checked_color if glowing else None)

    @Property(float, notify=__position_changed)
    def position(self) -> float:
        """Return current position.

        Returns:
            The knob's current x-offset within the track.
        """
        return self.__position

    @position.setter
    def position(self, value: float) -> None:
        """Update the knob's x-offset, clamped to the track, and repaint.

        Args:
            value: The knob's new, unclamped x-offset.
        """
        value = max(self.__offset, min(self.__width - self.__knob_size - self.__offset, value))
        if value == self.__position:
            return
        self.__position = value
        self.__position_changed.emit(value)
        self.update()

    @override
    def sizeHint(self) -> QSize:
        """Return the switch's preferred size.

        Returns:
            The fixed track width and height.
        """
        return QSize(self.__width, self.__height)

    @override
    def hitButton(self, pos: QPoint, /) -> bool:
        """Return whether pos is within the clickable track area.

        Args:
            pos: The position to test, in widget coordinates.

        Returns:
            True if pos falls inside the track.
        """
        return self.rect().contains(pos)

    @override
    def paintEvent(self, _event: QPaintEvent) -> None:
        """Draw the track and knob at their current checked state/position.

        Args:
            _event: The Qt paint event; unused (paints based on internal state).
        """
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(DISABLED_OPACITY)
        track_rect: QRect = QRect(0, 0, self.width(), self.height())
        unchecked_color: QColor = Colors.BACKGROUND_2.value.qcolor
        radius: int = self.__width // 4
        painter.setBrush(self.__checked_color if self.isChecked() else unchecked_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(track_rect, radius, radius)
        painter.setPen(QColor(0, 0, 0, 30))
        painter.setBrush(self.__knob_color)
        painter.drawEllipse(QRect(int(self.__position), self.__offset, self.__knob_size,
                                  self.__knob_size))
        painter.end()

    @Slot()
    def __start_animation(self, /) -> None:
        """Animate the knob to the on/off stop matching the current checked state."""
        self.__animation.stop()
        self.__animation.setStartValue(self.__position)
        if self.isChecked():
            self.__animation.setEndValue(self.__width - self.__knob_size - self.__offset)
        else:
            self.__animation.setEndValue(self.__offset)
        self.__animation.start()

if __name__ == "__main__":
    ...
