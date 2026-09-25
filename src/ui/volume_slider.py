"""Volume slider widget."""

from typing import override

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSlider, QWidget

from ui.glow import draw_segmented_bar
from utils.common import Colors, active_skin, theme_bus

SEGMENTED_BAR_HEIGHT = 8.0


class Volume(QSlider):
    """Volume slider widget.

    HUD skins paint it as a segmented LED level meter (no handle) that jumps
    to wherever it's clicked/dragged; other skins use the QSS-styled slider.
    """

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize Volume slider widget.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.setOrientation(Qt.Orientation.Horizontal)
        self.setRange(0, 127)
        self.setValue(100)
        self.set_style()
        theme_bus.changed.connect(self.set_style)

    def set_style(self) -> None:
        """Apply the gradient-filled track and handle styling."""
        self.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {Colors.BACKGROUND_2.value.hex};
                border: none;
                border-radius: 4px;
                height: 8px;
            }}
            QSlider::handle:horizontal {{
                background: {Colors.WHITE.value.hex};
                border: none;
                border-radius: 8px;
                width: 16px;
                height: 16px;
                margin: -4px 0;
            }}
            QSlider::handle:horizontal:hover {{
                background: {Colors.HIGHLIGHT.value.hex};
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.VOLUME.value.hex}, stop:1 {Colors.HIGHLIGHT.value.hex}
                );
                border-radius: 4px;
            }}
        """)
        self.update()

    def __set_value_at(self, x: float) -> None:
        """Set the value matching horizontal position x, for the handle-less HUD meter.

        Args:
            x: The horizontal position within the widget, in pixels.
        """
        fraction: float = max(0.0, min(1.0, x / max(1, self.width())))
        self.setValue(round(self.minimum() + fraction * (self.maximum() - self.minimum())))

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Jump to the clicked level on HUD skins; default slider behavior otherwise.

        Args:
            event: The Qt mouse press event.
        """
        if active_skin().hud and event.button() == Qt.MouseButton.LeftButton:
            self.__set_value_at(event.position().x())
            return
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Follow a left-button drag on HUD skins; default slider behavior otherwise.

        Args:
            event: The Qt mouse move event.
        """
        if active_skin().hud and event.buttons() & Qt.MouseButton.LeftButton:
            self.__set_value_at(event.position().x())
            return
        super().mouseMoveEvent(event)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint a segmented LED meter on HUD skins; the QSS-styled slider otherwise.

        Args:
            event: The Qt paint event.
        """
        if not active_skin().hud:
            super().paintEvent(event)
            return
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Inset horizontally so the lit span's glow isn't clipped at the ends.
        bar: QRectF = QRectF(3, (self.height() - SEGMENTED_BAR_HEIGHT) / 2,
                             self.width() - 6, SEGMENTED_BAR_HEIGHT)
        fraction: float = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        draw_segmented_bar(painter, bar, fraction,
                           (Colors.VOLUME.value.qcolor, Colors.HIGHLIGHT.value.qcolor),
                           Colors.BACKGROUND_2.value.qcolor, active_skin().neon_glow)
        painter.end()

if __name__ == "__main__":
    ...
