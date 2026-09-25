"""ProgressBar widget: custom-painted track + hover-reveal thumb, click/drag to seek."""

from typing import override

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QEnterEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QProgressBar, QWidget

from ui.animation import AnimatedProgress
from ui.glow import draw_segmented_bar
from utils.common import Colors, active_skin, theme_bus
from utils.skins import Skin

HIT_AREA_HEIGHT = 18
TRACK_HEIGHT = 6
THUMB_RADIUS = 6.0
THUMB_HOVER_DURATION_MS = 120
FILL_ANIMATION_DURATION_MS = 950


class ProgressBar(QProgressBar):
    """Custom-painted progress bar with a thumb that only appears on hover."""

    seek_requested: Signal = Signal(int)

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize ProgressBar.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.setMinimum(0)
        self.setMaximum(100)
        self.setFixedHeight(HIT_AREA_HEIGHT)
        self.setOrientation(Qt.Orientation.Horizontal)
        self.setTextVisible(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QProgressBar { background: transparent; border: none; }")
        self.__thumb_reveal: AnimatedProgress = AnimatedProgress(
            self, self.__on_reveal_changed, THUMB_HOVER_DURATION_MS)
        self.__fill: AnimatedProgress = AnimatedProgress(
            self, self.__on_fill_changed, FILL_ANIMATION_DURATION_MS,
            easing=QEasingCurve.Type.Linear)
        theme_bus.changed.connect(self.update)

    def __on_reveal_changed(self, _value: float) -> None:
        """Repaint as the thumb-reveal animation progresses.

        Args:
            _value: The animation's current progress (0..1); unused, since
                painting reads the reveal value directly.
        """
        self.update()

    def __on_fill_changed(self, _value: float) -> None:
        """Repaint as the fill animation progresses.

        Args:
            _value: The animation's current progress (0..1); unused, since
                painting reads the fill value directly.
        """
        self.update()

    @override
    def setValue(self, value: int) -> None:
        """Set the progress value, animating the visual fill smoothly forward.

        A backward jump (new track, error reset) snaps instantly instead of
        visually rewinding.

        Args:
            value: The new progress value.
        """
        old_fraction: float = self.__fraction()
        super().setValue(value)
        new_fraction: float = self.__fraction()
        if new_fraction < old_fraction:
            self.__fill.snap_to(new_fraction)
        else:
            self.__fill.animate_to(new_fraction)

    def __track_rect(self) -> QRectF:
        """Return the visual track rect, vertically centered in the hit area.

        Returns:
            The track's bounding rect.
        """
        return QRectF(0, (self.height() - TRACK_HEIGHT) / 2, self.width(), TRACK_HEIGHT)

    def __fraction(self) -> float:
        """Return current progress as a 0..1 fraction, guarding against a zero-range bar.

        Returns:
            The current progress as a 0..1 fraction.
        """
        span: int = self.maximum() - self.minimum()
        return 0.0 if span <= 0 else (self.value() - self.minimum()) / span

    def __value_at(self, x: float) -> int:
        """Return the progress value corresponding to an x coordinate within the bar.

        Args:
            x: An x coordinate within the bar's local geometry.

        Returns:
            The corresponding progress value, clamped to [minimum, maximum].
        """
        fraction: float = 0.0 if self.width() <= 0 else max(0.0, min(1.0, x / self.width()))
        return self.minimum() + round(fraction * (self.maximum() - self.minimum()))

    def __seek_to(self, x: float) -> None:
        """Snap the fill to x and emit seek_requested with the corresponding value.

        Args:
            x: An x coordinate within the bar's local geometry.
        """
        value: int = self.__value_at(x)
        self.setValue(value)
        self.seek_requested.emit(value)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Seek to the clicked position.

        Args:
            event: The Qt mouse press event.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.__seek_to(event.position().x())
            return
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Continue seeking while dragging with the left button held.

        Args:
            event: The Qt mouse move event.
        """
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.__seek_to(event.position().x())
            return
        super().mouseMoveEvent(event)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        """Reveal the thumb on hover.

        Args:
            event: The Qt enter event.
        """
        self.__thumb_reveal.animate_to(1.0)
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Hide the thumb when the mouse leaves.

        Args:
            event: The Qt leave event.
        """
        self.__thumb_reveal.animate_to(0.0)
        super().leaveEvent(event)

    @override
    def paintEvent(self, _event: QPaintEvent) -> None:
        """Paint the track, filled portion, and (if hovered) the thumb.

        HUD skins draw the track as a segmented LED level bar instead.

        Args:
            _event: The Qt paint event; unused (paints based on internal state).
        """
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track: QRectF = self.__track_rect()
        radius: float = TRACK_HEIGHT / 2
        painter.setPen(Qt.PenStyle.NoPen)
        fraction: float = self.__fill.value
        skin: Skin = active_skin()
        if skin.hud:
            draw_segmented_bar(painter, track, fraction,
                               (Colors.ACCENT_1.value.qcolor, Colors.HIGHLIGHT.value.qcolor),
                               Colors.BACKGROUND_2.value.qcolor, skin.neon_glow)
        else:
            painter.setBrush(QColor(Colors.BACKGROUND_2.value.hex))
            painter.drawRoundedRect(track, radius, radius)
        if fraction > 0 and not skin.hud:
            fill: QRectF = QRectF(track)
            fill.setWidth(track.width() * fraction)
            gradient: QLinearGradient = QLinearGradient(fill.topLeft(), fill.topRight())
            gradient.setColorAt(0.0, QColor(Colors.ACCENT_1.value.hex))
            gradient.setColorAt(1.0, QColor(Colors.HIGHLIGHT.value.hex))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(fill, radius, radius)
        if self.__thumb_reveal.value > 0:
            center_x: float = track.left() + track.width() * fraction
            center_y: float = track.center().y()
            thumb_color: QColor = QColor(Colors.WHITE.value.hex)
            thumb_color.setAlpha(int(255 * self.__thumb_reveal.value))
            painter.setBrush(thumb_color)
            painter.drawEllipse(QPointF(center_x, center_y), THUMB_RADIUS, THUMB_RADIUS)

if __name__ == "__main__":
    ...
