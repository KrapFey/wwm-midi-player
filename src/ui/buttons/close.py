"""Close Button widget."""

from typing import override

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ui.buttons.abstract import AbstractButton
from utils.common import Colors, active_skin

SIZE = QSize(28, 28)
HOVER_BACKGROUND_ALPHA = 180


class CloseButton(AbstractButton):
    """Close Button widget for the custom title bar."""

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize Close Button widget.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent, size=SIZE)
        self.setToolTip("Close")

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the button's rounded-square background and "×" glyph.

        Args:
            event: The Qt paint event.
        """
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect: QRectF = self._scaled_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        alpha: int = int(HOVER_BACKGROUND_ALPHA * self._hover_progress())
        painter.setBrush(self._background_color(alpha, base=Colors.RED.value.qcolor))
        radius: int = active_skin().radius_sm
        painter.drawRoundedRect(rect, radius, radius)
        glyph_base = Colors.WHITE.value.qcolor if self._hover_progress() > 0.5 else None
        pen: QPen = QPen(self._draw_color(glyph_base))
        pen.setWidth(2)
        painter.setPen(pen)
        inset: QRectF = rect.adjusted(rect.width() * 0.30, rect.height() * 0.30,
                                      -rect.width() * 0.30, -rect.height() * 0.30)
        painter.drawLine(QPointF(inset.left(), inset.top()), QPointF(inset.right(), inset.bottom()))
        painter.drawLine(QPointF(inset.right(), inset.top()), QPointF(inset.left(), inset.bottom()))
        painter.end()
        return super().paintEvent(event)

if __name__ == "__main__":
    ...
