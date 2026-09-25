"""Minimize Button widget."""

from typing import override

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ui.buttons.abstract import AbstractButton
from utils.common import active_skin

SIZE = QSize(28, 28)
HOVER_BACKGROUND_ALPHA = 40


class MinimizeButton(AbstractButton):
    """Minimize Button widget for the custom title bar."""

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize Minimize Button widget.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent, size=SIZE)
        self.setToolTip("Minimize")

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the button's background and minimize glyph.

        Args:
            event: The Qt paint event.
        """
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect: QRectF = self._scaled_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        alpha: int = int(HOVER_BACKGROUND_ALPHA * self._hover_progress())
        painter.setBrush(self._background_color(alpha))
        radius: int = active_skin().radius_sm
        painter.drawRoundedRect(rect, radius, radius)
        pen: QPen = QPen(self._draw_color())
        pen.setWidth(2)
        painter.setPen(pen)
        y: float = rect.center().y()
        painter.drawLine(int(rect.left() + rect.width() * 0.28), int(y),
                          int(rect.right() - rect.width() * 0.28), int(y))
        painter.end()
        return super().paintEvent(event)

if __name__ == "__main__":
    ...
