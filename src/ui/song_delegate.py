"""Item delegate painting modern two-line (title/artist) rows for the song list."""

from typing import override

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPolygonF
from PySide6.QtWidgets import QListWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ui.animation import AnimatedProgress
from utils.common import Colors, active_skin, theme_bus

TITLE_ROLE: int = Qt.ItemDataRole.UserRole + 1
ARTIST_ROLE: int = Qt.ItemDataRole.UserRole + 2

HOVER_DURATION_MS = 120
PRESS_DURATION_MS = 80
HOVER_MAX_ALPHA = 140
PRESS_EXTRA_ALPHA = 40
NOW_PLAYING_ALPHA = 45

ROW_H_MARGIN = 4.0
ROW_V_MARGIN = 3.0
ROW_INNER_VPADDING = 8.0
LINE_GAP = 2.0
SELECTION_GUTTER_WIDTH = 8.0
PLAY_GUTTER_WIDTH = 20.0
TEXT_PADDING = 8.0


class SongDelegate(QStyledItemDelegate):
    """Paints each row's title/artist, now-playing glyph, and animated hover/press/selection."""

    def __init__(self, view: QListWidget, accent: Colors, parent: QObject|None=None) -> None:
        """Initialize the delegate and wire hover/press tracking on view.

        Args:
            view: The list widget this delegate paints rows for; also the
                source of hover/press mouse tracking.
            accent: The accent color used for the now-playing glyph and
                selection bar.
            parent: Optional parent object.
        """
        super().__init__(parent=parent)
        self.__view: QListWidget = view
        self.__accent_color: QColor = accent.value.qcolor
        self.__title_font: QFont
        self.__artist_font: QFont
        self.__title_metrics: QFontMetrics
        self.__artist_metrics: QFontMetrics
        self.__build_fonts()
        self.__hovered_row: int = -1
        self.__pressed_row: int = -1
        self.__now_playing_row: int = -1
        self.__hover: AnimatedProgress = AnimatedProgress(
            self, self.__on_progress_changed, HOVER_DURATION_MS)
        self.__press: AnimatedProgress = AnimatedProgress(
            self, self.__on_progress_changed, PRESS_DURATION_MS)
        view.viewport().setMouseTracking(True)
        view.entered.connect(self.__on_entered)
        view.viewport().installEventFilter(self)
        theme_bus.changed.connect(self.__on_theme_changed)

    def __build_fonts(self) -> None:
        """(Re)build the title/artist fonts from the current app font family.

        QFont() snapshots the app font at construction, so a skin with its
        own font family needs these rebuilt rather than set once.
        """
        self.__title_font = QFont()
        self.__title_font.setBold(True)
        self.__title_font.setPixelSize(14)
        self.__artist_font = QFont()
        self.__artist_font.setPixelSize(12)
        self.__title_metrics = QFontMetrics(self.__title_font)
        self.__artist_metrics = QFontMetrics(self.__artist_font)

    def __on_theme_changed(self) -> None:
        """Pick up a skin's font change, then re-lay out rows (heights may change) and repaint."""
        self.__build_fonts()
        self.__view.doItemsLayout()
        self.__view.viewport().update()

    def set_now_playing_row(self, row: int) -> None:
        """Mark row as the now-playing track (or -1 for none) and repaint.

        Args:
            row: The now-playing row index, or -1 if nothing is playing.
        """
        self.__now_playing_row = row
        self.__view.viewport().update()

    @override
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Reset hover/press state on viewport leave and track press/release.

        Args:
            obj: The watched object (the list view's viewport).
            event: The event being filtered.

        Returns:
            The base class's handling result.
        """
        if event.type() == QEvent.Type.Leave:
            self.__hovered_row = -1
            self.__hover.animate_to(0.0)
        elif event.type() == QEvent.Type.MouseButtonPress:
            row: int = self.__view.indexAt(event.position().toPoint()).row()
            self.__pressed_row = row
            self.__press.snap_to(0.0)
            self.__press.animate_to(1.0)
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self.__press.animate_to(0.0)
        return super().eventFilter(obj, event)

    def __on_entered(self, index: QModelIndex) -> None:
        """Snap the previously-hovered row to 0 and animate the newly-hovered row 0->1.

        Args:
            index: The model index the mouse just entered.
        """
        if index.row() == self.__hovered_row:
            return
        self.__hovered_row = index.row()
        self.__hover.snap_to(0.0)
        self.__hover.animate_to(1.0)

    def __on_progress_changed(self, _value: float) -> None:
        """Repaint the viewport as hover/press progress changes.

        Args:
            _value: The animation's current progress (0..1); unused, since
                painting reads the hover/press values directly.
        """
        self.__view.viewport().update()

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Return a row height that fits both the title and artist lines.

        Args:
            option: The style options for the item.
            index: The model index being sized.

        Returns:
            The row's preferred size.
        """
        title_height: int = self.__title_metrics.height()
        artist_height: int = self.__artist_metrics.height()
        block_height: float = title_height + LINE_GAP + artist_height
        row_height: float = block_height + 2 * ROW_INNER_VPADDING + 2 * ROW_V_MARGIN
        base: QSize = super().sizeHint(option, index)
        return QSize(base.width(), int(row_height))

    def __draw_now_playing_glyph(self, painter: QPainter, center_x: float, center_y: float) -> None:
        """Draw a small solid play-triangle marking the now-playing row.

        Args:
            painter: The active painter to draw with.
            center_x: The glyph's horizontal center.
            center_y: The glyph's vertical center.
        """
        size: float = 5.0
        points: list[QPointF] = [
            QPointF(center_x - size * 0.6, center_y - size),
            QPointF(center_x - size * 0.6, center_y + size),
            QPointF(center_x + size * 0.8, center_y),
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.__accent_color)
        painter.drawPolygon(QPolygonF(points))

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
                    index: QModelIndex) -> None:
        """Fully paint the row: background/selection/now-playing tints, glyph, title, artist.

        Args:
            painter: The active painter to draw with.
            option: The style options for the item, including its rect and
                selection state.
            index: The model index being painted.
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background_rect: QRectF = QRectF(option.rect).adjusted(
            ROW_H_MARGIN, ROW_V_MARGIN, -ROW_H_MARGIN, -ROW_V_MARGIN)
        row: int = index.row()
        is_now_playing: bool = row == self.__now_playing_row
        radius: float = active_skin().radius_sm
        painter.setPen(Qt.PenStyle.NoPen)
        if is_now_playing:
            tint: QColor = QColor(Colors.ACCENT_1.value.qcolor)
            tint.setAlpha(NOW_PLAYING_ALPHA)
            painter.setBrush(tint)
            painter.drawRoundedRect(background_rect, radius, radius)
        if row == self.__hovered_row and self.__hover.value > 0:
            hover_tint: QColor = QColor(Colors.BACKGROUND_2.value.qcolor)
            hover_tint.setAlpha(int(HOVER_MAX_ALPHA * self.__hover.value))
            painter.setBrush(hover_tint)
            painter.drawRoundedRect(background_rect, radius, radius)
        if row == self.__pressed_row and self.__press.value > 0:
            press_tint: QColor = QColor(Colors.BLACK.value.qcolor)
            press_tint.setAlpha(int(PRESS_EXTRA_ALPHA * self.__press.value))
            painter.setBrush(press_tint)
            painter.drawRoundedRect(background_rect, radius, radius)
        if option.state & QStyle.StateFlag.State_Selected:
            bar_rect: QRectF = QRectF(background_rect.left() + 2, background_rect.top() + 2,
                                      3, background_rect.height() - 4)
            painter.setBrush(self.__accent_color)
            painter.drawRoundedRect(bar_rect, 1.5, 1.5)
        text_x: float = (background_rect.left() + SELECTION_GUTTER_WIDTH
                         + PLAY_GUTTER_WIDTH + TEXT_PADDING)
        text_width: float = background_rect.right() - text_x - TEXT_PADDING
        if is_now_playing:
            glyph_center_x: float = (background_rect.left() + SELECTION_GUTTER_WIDTH
                                     + PLAY_GUTTER_WIDTH / 2)
            self.__draw_now_playing_glyph(painter, glyph_center_x, background_rect.center().y())
        title_text: str = self.__title_metrics.elidedText(
            str(index.data(TITLE_ROLE) or ""), Qt.TextElideMode.ElideRight, int(text_width))
        artist_text: str = self.__artist_metrics.elidedText(
            str(index.data(ARTIST_ROLE) or ""), Qt.TextElideMode.ElideRight, int(text_width))
        title_top: float = background_rect.top() + ROW_INNER_VPADDING
        title_rect: QRectF = QRectF(text_x, title_top, text_width, self.__title_metrics.height())
        artist_rect: QRectF = QRectF(
            text_x, title_top + self.__title_metrics.height() + LINE_GAP,
            text_width, self.__artist_metrics.height())
        painter.setFont(self.__title_font)
        painter.setPen(self.__accent_color if is_now_playing else Colors.WHITE.value.qcolor)
        painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignVCenter), title_text)
        painter.setFont(self.__artist_font)
        painter.setPen(Colors.TEXT_MUTED.value.qcolor)
        painter.drawText(artist_rect, int(Qt.AlignmentFlag.AlignVCenter), artist_text)
        painter.restore()

if __name__ == "__main__":
    ...
