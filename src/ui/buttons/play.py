"""Play/Pause Button widget."""

from typing import override

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from ui.animation import AnimatedProgress
from ui.buttons.abstract import AbstractButton
from ui.glow import set_widget_glow
from utils.common import Colors, active_skin, theme_bus

PRIMARY_SIZE = QSize(52, 52)
PRIMARY_BACKGROUND_ALPHA = 255
GLYPH_COLOR = QColor("#FFFFFF")
MORPH_ANIMATION_DURATION_MS = 400


class PlayButton(AbstractButton):
    """Play/Pause Button widget."""

    change: Signal = Signal(bool)

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize Play/Pause Button widget.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent, size=PRIMARY_SIZE)
        self.__is_playing: bool = False
        self.__morph: AnimatedProgress = AnimatedProgress(
            self, self.__on_morph_changed, MORPH_ANIMATION_DURATION_MS)
        self.change.connect(self.__toggle_state)
        self.__sync_glow()
        theme_bus.changed.connect(self.__sync_glow)

    def __sync_glow(self) -> None:
        """Glow in the accent color on neon-glow skins; no effect otherwise."""
        glowing: bool = active_skin().neon_glow
        set_widget_glow(self, Colors.ACCENT_1.value.qcolor if glowing else None)

    def __on_morph_changed(self, _value: float) -> None:
        """Repaint as the play/pause morph animation progresses.

        Args:
            _value: The animation's current progress (0..1); unused, since
                painting reads the morph value directly.
        """
        self.update()

    @Slot(bool)
    def __toggle_state(self, new_state: bool) -> None:
        """Animate the glyph toward play or pause, if the state actually changed.

        Args:
            new_state: True to morph toward the pause glyph, False for play.
        """
        if self.__is_playing == new_state:
            return
        self.__is_playing = new_state
        self.__morph.animate_to(1.0 if new_state else 0.0)

    @override
    def paintEvent(self, _event: QPaintEvent) -> None:
        """Draw the button's circular background and play/pause glyph.

        Args:
            _event: The Qt paint event; unused (paints based on internal state).
        """
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle: QRectF = self._scaled_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._background_color(PRIMARY_BACKGROUND_ALPHA))
        painter.drawEllipse(circle)
        rect: QRectF = circle.adjusted(circle.width() * 0.30, circle.height() * 0.26,
                                       -circle.width() * 0.30, -circle.height() * 0.26)
        painter.setBrush(QBrush(GLYPH_COLOR))
        morph: float = self.__morph.value
        if morph < 0.5:
            p1: QPointF = rect.bottomLeft()
            p2: QPointF = rect.topLeft()
            p3: QPointF = QPointF(rect.right(), rect.center().y())
            p3.setX(p3.x() - (p3.x() - rect.center().x()) * (morph * 2))
            painter.drawPolygon([p1, p2, p3])
        else:
            bar_width: float = rect.width() / 3
            gap: float = rect.width() - (2 * bar_width)
            left_bar: QRectF = QRectF(rect.left(), rect.top(), bar_width, rect.height())
            right_bar: QRectF = QRectF(rect.left() + bar_width + gap, rect.top(), bar_width,
                                      rect.height())
            factor: float = (morph - 0.5) * 2
            left_bar.setWidth(left_bar.width() * factor)
            right_bar.setWidth(right_bar.width() * factor)
            painter.drawRect(left_bar)
            painter.drawRect(right_bar)

if __name__ == "__main__":
    ...
