"""Theme-aware combo box with a hand-drawn dropdown chevron."""

from typing import override

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QComboBox, QWidget

from utils.common import Colors, theme_bus

CHEVRON_WIDTH = 8.0
CHEVRON_HEIGHT = 4.5
CHEVRON_RIGHT_MARGIN = 12.0


class ComboBox(QComboBox):
    """QComboBox that paints its own chevron in the active palette's text color.

    Styling QComboBox::drop-down via QSS (needed to get rid of the native
    arrow box, which clashes with the app's flat look) also removes the
    native arrow, and QSS can't draw one without an image file - so the
    stylesheet hides the arrow entirely (see ui.dialog_style) and this
    paints a chevron on top instead, mirroring SearchBox's hand-drawn icons.
    """

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize ComboBox.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme_bus.changed.connect(self.update)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the styled combo box, then the chevron on top.

        Args:
            event: The Qt paint event.
        """
        super().paintEvent(event)
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color_hex: str = (Colors.WHITE if self.isEnabled() else Colors.TEXT_MUTED).value.hex
        pen: QPen = QPen(color_hex)
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        right: float = self.width() - CHEVRON_RIGHT_MARGIN
        center_y: float = self.height() / 2
        painter.drawPolyline([
            QPointF(right - CHEVRON_WIDTH, center_y - CHEVRON_HEIGHT / 2),
            QPointF(right - CHEVRON_WIDTH / 2, center_y + CHEVRON_HEIGHT / 2),
            QPointF(right, center_y - CHEVRON_HEIGHT / 2),
        ])
        painter.end()

if __name__ == "__main__":
    ...
