"""Maximize/Restore Button widget."""

from typing import override

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ui.buttons.abstract import AbstractButton
from utils.common import active_skin

SIZE = QSize(28, 28)
HOVER_BACKGROUND_ALPHA = 40


class MaximizeButton(AbstractButton):
    """Maximize/Restore Button widget for the custom title bar.

    Reflects actual window state rather than driving it directly: the
    window can become (un)maximized without this button being clicked
    (Aero-snap, Win+Up, double-click, drag-restore), so callers must push
    state in via set_maximized() instead of relying on a checked state.
    """

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize Maximize Button widget.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent, size=SIZE)
        self.__maximized: bool = False
        self.setToolTip("Maximize")

    @property
    def maximized(self) -> bool:
        """Return whether the button currently reflects a maximized window.

        Returns:
            True if reflecting a maximized window, False otherwise.
        """
        return self.__maximized

    def set_maximized(self, maximized: bool) -> None:
        """Update the reflected window state and repaint.

        Args:
            maximized: Whether the window is currently maximized.
        """
        if maximized == self.__maximized:
            return
        self.__maximized = maximized
        self.setToolTip("Restore" if maximized else "Maximize")
        self.update()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the button's background and maximize/restore glyph.

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
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.__maximized:
            back: QRectF = rect.adjusted(rect.width() * 0.32, rect.height() * 0.22,
                                        -rect.width() * 0.22, -rect.height() * 0.32)
            front: QRectF = rect.adjusted(rect.width() * 0.22, rect.height() * 0.32,
                                         -rect.width() * 0.32, -rect.height() * 0.22)
            painter.drawRect(back)
            painter.drawRect(front)
        else:
            square: QRectF = rect.adjusted(rect.width() * 0.26, rect.height() * 0.26,
                                           -rect.width() * 0.26, -rect.height() * 0.26)
            painter.drawRect(square)
        painter.end()
        return super().paintEvent(event)

if __name__ == "__main__":
    ...
