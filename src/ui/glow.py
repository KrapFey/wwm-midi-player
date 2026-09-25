"""Shared neon-glow and segmented-LED painting helpers for skins that use them."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# Translucent halos drawn behind a shape, as (spread in px, alpha) from
# outermost to innermost - reads as a soft outer glow rather than a hard edge.
GLOW_LAYERS: tuple[tuple[float, int], ...] = ((5.0, 22), (2.5, 55))
WIDGET_GLOW_BLUR: float = 14.0
WIDGET_GLOW_ALPHA: int = 170
SEGMENT_WIDTH: float = 4.0
SEGMENT_GAP: float = 2.0


def draw_glow(painter: QPainter, rect: QRectF, color: QColor, radius: float) -> None:
    """Draw GLOW_LAYERS translucent halos around rect.

    Call before drawing the shape itself, so the shape sits on its glow.

    Args:
        painter: The active painter to draw with.
        rect: The shape being haloed.
        color: The glow color; alpha is overridden per layer.
        radius: rect's own corner radius; halos grow it by their spread.
    """
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for spread, alpha in GLOW_LAYERS:
        halo: QColor = QColor(color)
        halo.setAlpha(alpha)
        painter.setBrush(halo)
        painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread),
                                radius + spread, radius + spread)
    painter.restore()


def set_widget_glow(widget: QWidget, color: QColor|None) -> None:
    """Give everything widget renders (text, shapes) a soft neon outer glow, or remove it.

    Uses a graphics effect rather than painted halos because an effect may
    draw outside the widget's own rect, so the glow isn't clipped at its
    edges - needed for tightly-sized widgets like toggles and buttons.

    Args:
        widget: The widget whose rendered content should glow.
        color: The glow color, or None to remove any existing glow.
    """
    if color is None:
        widget.setGraphicsEffect(None)
        return
    glow: QColor = QColor(color)
    glow.setAlpha(WIDGET_GLOW_ALPHA)
    effect: QGraphicsDropShadowEffect = QGraphicsDropShadowEffect(widget)
    effect.setOffset(0, 0)
    effect.setBlurRadius(WIDGET_GLOW_BLUR)
    effect.setColor(glow)
    widget.setGraphicsEffect(effect)


def draw_segmented_bar(painter: QPainter, rect: QRectF, fraction: float,
                       colors: tuple[QColor, QColor], unlit: QColor, glow: bool) -> None:
    """Draw a segmented LED-style level bar filled to fraction.

    Lit segments take their color from a start->end gradient spanning the
    whole bar (so a segment's color also encodes its position), and unlit
    segments stay visible as a dim track.

    Args:
        painter: The active painter to draw with.
        rect: The bar's bounding rect.
        fraction: How much of the bar is lit, 0..1.
        colors: The (start, end) colors of the lit gradient.
        unlit: The color of unlit segments.
        glow: Whether to draw a soft glow behind the lit span.
    """
    count: int = max(1, int((rect.width() + SEGMENT_GAP) / (SEGMENT_WIDTH + SEGMENT_GAP)))
    # Spread the leftover width over the gaps so the bar spans rect exactly.
    gap: float = (rect.width() - count * SEGMENT_WIDTH) / max(1, count - 1)
    lit: int = round(max(0.0, min(1.0, fraction)) * count)
    gradient: QLinearGradient = QLinearGradient(rect.topLeft(), rect.topRight())
    gradient.setColorAt(0.0, colors[0])
    gradient.setColorAt(1.0, colors[1])
    painter.save()
    if glow and lit:
        lit_width: float = lit * SEGMENT_WIDTH + (lit - 1) * gap
        mid: QColor = QColor(colors[0])
        mid.setRgbF((colors[0].redF() + colors[1].redF()) / 2,
                    (colors[0].greenF() + colors[1].greenF()) / 2,
                    (colors[0].blueF() + colors[1].blueF()) / 2)
        draw_glow(painter, QRectF(rect.left(), rect.top(), lit_width, rect.height()), mid, 1.0)
    painter.setPen(Qt.PenStyle.NoPen)
    for index in range(count):
        segment: QRectF = QRectF(rect.left() + index * (SEGMENT_WIDTH + gap), rect.top(),
                                 SEGMENT_WIDTH, rect.height())
        painter.setBrush(gradient if index < lit else unlit)
        painter.drawRoundedRect(segment, 1.0, 1.0)
    painter.restore()
