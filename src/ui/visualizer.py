"""Synthesia-style falling-note piano visualizer panel."""

import bisect
import math
from typing import override

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from ui.glow import draw_glow
from utils.common import Colors, active_skin, note_color_hex, resolve_font_family, theme_bus
from utils.note_events import NoteEvent
from utils.piano_layout import (
    MIDI_NOTE_MAX,
    MIDI_NOTE_MIN,
    clamp_note,
    is_white_key,
    key_width,
    key_x_position,
)
from utils.skins import PianoColors, Skin

KEYBOARD_HEIGHT_RATIO: float = 0.22
LOOKAHEAD_SECONDS: float = 3.0
MIN_BAR_HEIGHT: float = 3.0
BAR_MARGIN_RATIO: float = 0.12
BAR_CORNER_RADIUS: float = 5.0
KEY_CORNER_RADIUS: float = 3.0
BLACK_KEY_HEIGHT_RATIO: float = 0.62
HIT_LINE_HEIGHT: float = 3.0

# HUD skins: telemetry grid rows every GRID_STEP_SECONDS (brighter on whole
# seconds) scrolling with playback, plus octave columns at every C key.
GRID_STEP_SECONDS: float = 0.5
GRID_MINOR_ALPHA: int = 90
GRID_MAJOR_ALPHA: int = 200
# HUD skins: live readout chips along the top of the falling-notes area.
TELEMETRY_MARGIN: float = 12.0
TELEMETRY_SPACING: float = 8.0
TELEMETRY_PADDING: float = 9.0
TELEMETRY_FONT_PX: int = 10
TELEMETRY_DOT_SIZE: float = 6.0
TELEMETRY_CHIP_ALPHA: int = 200
DENSITY_WINDOW_SECONDS: float = 1.0


class PianoVisualizer(QWidget):
    """Draws an 88-key keyboard with falling note bars synced to playback position."""

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize PianoVisualizer.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.__events: list[NoteEvent] = []
        self.__starts: list[float] = []
        self.__max_note_duration: float = 0.0
        self.__duration: float = 0.0
        self.__position: float = 0.0
        self.__muted_tracks: set[int] = set()
        self.__geometry_width: float = -1.0
        self.__key_geometry: dict[int, tuple[float, float]] = {}
        self.__tracks: set[int] = set()
        self.__telemetry_font: QFont = QFont()
        self.__on_theme_changed()
        theme_bus.changed.connect(self.__on_theme_changed)
        self.setAutoFillBackground(False)

    def __on_theme_changed(self) -> None:
        """Re-resolve the skin's telemetry font (once per switch, not per frame) and repaint."""
        self.__telemetry_font = QFont()
        family: str = resolve_font_family(active_skin().mono_families)
        if family:
            self.__telemetry_font.setFamily(family)
        self.__telemetry_font.setPixelSize(TELEMETRY_FONT_PX)
        self.update()

    def load_notes(self, events: list[NoteEvent], duration: float) -> None:
        """Replace the current note set for a newly-loaded track and reset scroll.

        Args:
            events: The note events to visualize, pre-sorted by start time.
            duration: The track's total duration in seconds.
        """
        self.__events = events
        self.__starts = [event.start for event in events]
        self.__max_note_duration = max((event.end - event.start for event in events), default=0.0)
        self.__tracks = {event.track for event in events}
        self.__duration = duration
        self.__position = 0.0
        self.update()

    def set_position(self, seconds: float) -> None:
        """Update the current playback time; triggers a repaint.

        Args:
            seconds: The current playback position in seconds.
        """
        self.__position = seconds
        self.update()

    def set_muted_tracks(self, tracks: set[int]) -> None:
        """Hide falling notes/keyboard highlights for the given tracks; repaints immediately.

        Args:
            tracks: The indices of tracks to hide.
        """
        self.__muted_tracks = tracks
        self.update()

    def clear(self) -> None:
        """Reset to the empty/idle state (stop, track switch, playlist clear)."""
        self.__events = []
        self.__starts = []
        self.__max_note_duration = 0.0
        self.__tracks = set()
        self.__duration = 0.0
        self.__position = 0.0
        self.__muted_tracks = set()
        self.update()

    def __ensure_key_geometry(self) -> None:
        """(Re)compute per-note (x, width) once per width change, not every frame.

        key_x_position()/white_key_index() do an O(range) scan per call; calling
        them for all 88 notes on every paintEvent (30fps) was the main source of
        visible animation stutter. The geometry only actually changes when the
        widget is resized, so cache it and recompute only then.
        """
        width: float = self.width()
        if width == self.__geometry_width:
            return
        self.__geometry_width = width
        self.__key_geometry = {
            note: (key_x_position(note, width), key_width(note, width))
            for note in range(MIDI_NOTE_MIN, MIDI_NOTE_MAX + 1)
        }

    def __visible_events(self) -> list[NoteEvent]:
        """Return events that overlap the current lookahead window, cheaply.

        self.__events is pre-sorted by start time (utils.note_events.build_note_events
        guarantees this), so a bisect finds the first note that could still be visible;
        the scan then stops as soon as a note starts beyond the window instead of
        walking the whole file every frame. The bisect target is pushed back by
        self.__max_note_duration (not just the 0.5s margin) so a long/sustained note
        that started well before the window - but is still sounding - isn't skipped:
        bisecting on window_start alone would cut it off mid-fall as soon as its start
        time fell behind the window.

        Returns:
            The note events overlapping the current lookahead window, with
            muted tracks filtered out.
        """
        window_start: float = self.__position - 0.5
        window_end: float = self.__position + LOOKAHEAD_SECONDS
        lookback: float = window_start - self.__max_note_duration
        first_index: int = bisect.bisect_left(self.__starts, lookback)
        visible: list[NoteEvent] = []
        for event in self.__events[first_index:]:
            if event.start > window_end:
                break
            if event.track in self.__muted_tracks:
                continue
            if event.end >= window_start:
                visible.append(event)
        return visible

    def __draw_falling_notes(self, painter: QPainter, fall_rect: QRectF,
                                   visible: list[NoteEvent]) -> None:
        """Draw one bar per visible note, colored by originating track.

        Bars are inset from the full key width so adjacent notes read as
        distinct blocks, and shaded with a vertical gradient that brightens
        toward the keyboard to suggest motion toward the strike line.

        Args:
            painter: The active painter to draw with.
            fall_rect: The bounding rect of the falling-notes area.
            visible: This frame's visible note events (see __visible_events).
        """
        pixels_per_second: float = fall_rect.height() / LOOKAHEAD_SECONDS
        skin: Skin = active_skin()
        for event in visible:
            note: int = clamp_note(event.note)
            x, width = self.__key_geometry[note]
            top: float = fall_rect.bottom() - (event.end - self.__position) * pixels_per_second
            bottom: float = (fall_rect.bottom()
                              - (event.start - self.__position) * pixels_per_second)
            top = max(top, fall_rect.top())
            bottom = min(bottom, fall_rect.bottom())
            if bottom - top < MIN_BAR_HEIGHT:
                bottom = top + MIN_BAR_HEIGHT
            margin: float = max(1.0, width * BAR_MARGIN_RATIO)
            bar_rect: QRectF = QRectF(x + margin, top, width - margin * 2, bottom - top)
            base_color: QColor = QColor(note_color_hex(event.track, event.is_drum))
            radius: float = min(BAR_CORNER_RADIUS, skin.radius_sm, bar_rect.width() / 2)
            # Only notes sounding right now glow - they "light up" as they hit
            # the keys. Haloing every falling bar costs ~2x the whole frame on
            # dense files (each halo re-fills the full bar area), blowing the
            # 33ms frame budget.
            if skin.neon_glow and event.start <= self.__position <= event.end:
                draw_glow(painter, bar_rect, base_color, radius)
            gradient: QLinearGradient = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomLeft())
            gradient.setColorAt(0.0, base_color.darker(125))
            gradient.setColorAt(1.0, base_color.lighter(135))
            painter.setPen(QPen(base_color.lighter(160), 1))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(bar_rect, radius, radius)

    def __sounding_notes(self, visible: list[NoteEvent]) -> dict[int, str]:
        """Return clamped note numbers currently sounding, mapped to their track color.

        Args:
            visible: This frame's visible note events (see __visible_events).

        Returns:
            A mapping of clamped MIDI note number to its track's hex color
            for every note currently sounding.
        """
        sounding: dict[int, str] = {}
        for event in visible:
            if event.start <= self.__position <= event.end:
                sounding[clamp_note(event.note)] = note_color_hex(event.track, event.is_drum)
        return sounding

    def __draw_hit_line(self, painter: QPainter, fall_rect: QRectF) -> None:
        """Draw a thin glowing line marking where falling notes strike the keys.

        Args:
            painter: The active painter to draw with.
            fall_rect: The bounding rect of the falling-notes area.
        """
        line_rect: QRectF = QRectF(fall_rect.left(), fall_rect.bottom() - HIT_LINE_HEIGHT,
                                    fall_rect.width(), HIT_LINE_HEIGHT)
        # Copy rather than mutate the shared Colors.ACCENT_1 QColor instance in place.
        color: QColor = QColor(Colors.ACCENT_1.value.qcolor)
        if active_skin().neon_glow:
            draw_glow(painter, line_rect, color, 0.0)
        color.setAlpha(160)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(line_rect)

    def __draw_white_keys(self, painter: QPainter, keyboard_rect: QRectF,
                                sounding: dict[int, str]) -> None:
        """Draw the white keys with a subtle top-to-bottom shading for depth.

        Args:
            painter: The active painter to draw with.
            keyboard_rect: The bounding rect of the keyboard area.
            sounding: Mapping of currently-sounding clamped note number to
                its track's hex color, used to highlight active keys.
        """
        skin: Skin = active_skin()
        piano: PianoColors = skin.piano
        radius: float = min(KEY_CORNER_RADIUS, skin.radius_sm)
        painter.setPen(QPen(QColor(piano.border or Colors.BACKGROUND.value.hex), 1))
        for note in range(MIDI_NOTE_MIN, MIDI_NOTE_MAX + 1):
            if not is_white_key(note):
                continue
            x, width = self.__key_geometry[note]
            rect: QRectF = QRectF(x, keyboard_rect.top(), width, keyboard_rect.height())
            gradient: QLinearGradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if note in sounding:
                glow: QColor = QColor(sounding[note])
                gradient.setColorAt(0.0, glow.lighter(150))
                gradient.setColorAt(1.0, glow)
            else:
                gradient.setColorAt(0.0, QColor(piano.white_top))
                gradient.setColorAt(1.0, QColor(piano.white_bottom))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(rect, radius, radius)

    def __draw_black_keys(self, painter: QPainter, keyboard_rect: QRectF,
                                sounding: dict[int, str]) -> None:
        """Draw the black keys on top of the white keys, shaded for depth.

        Args:
            painter: The active painter to draw with.
            keyboard_rect: The bounding rect of the keyboard area.
            sounding: Mapping of currently-sounding clamped note number to
                its track's hex color, used to highlight active keys.
        """
        black_height: float = keyboard_rect.height() * BLACK_KEY_HEIGHT_RATIO
        skin: Skin = active_skin()
        piano: PianoColors = skin.piano
        radius: float = min(KEY_CORNER_RADIUS, skin.radius_sm)
        # Dark-keyed skins outline black keys too, or they vanish into equally
        # dark white keys; the default white-keyed piano doesn't need it.
        if piano.border:
            painter.setPen(QPen(QColor(piano.border), 1))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        for note in range(MIDI_NOTE_MIN, MIDI_NOTE_MAX + 1):
            if is_white_key(note):
                continue
            x, width = self.__key_geometry[note]
            rect: QRectF = QRectF(x, keyboard_rect.top(), width, black_height)
            gradient: QLinearGradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if note in sounding:
                glow: QColor = QColor(sounding[note])
                gradient.setColorAt(0.0, glow.lighter(140))
                gradient.setColorAt(1.0, glow.darker(110))
            else:
                gradient.setColorAt(0.0, QColor(piano.black_top))
                gradient.setColorAt(1.0, QColor(piano.black_bottom))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(rect, radius, radius)

    def __draw_keyboard(self, painter: QPainter, keyboard_rect: QRectF,
                              sounding: dict[int, str]) -> None:
        """Draw white keys, then black keys on top, highlighting sounding notes.

        Args:
            painter: The active painter to draw with.
            keyboard_rect: The bounding rect of the keyboard area.
            sounding: Mapping of currently-sounding clamped note number to
                its track's hex color, used to highlight active keys.
        """
        self.__draw_white_keys(painter, keyboard_rect, sounding)
        self.__draw_black_keys(painter, keyboard_rect, sounding)

    def __draw_grid(self, painter: QPainter, fall_rect: QRectF) -> None:
        """Draw the HUD telemetry grid behind the falling notes.

        Columns mark each octave (every C key); rows mark time, scrolling
        down with the notes, brighter on whole seconds.

        Args:
            painter: The active painter to draw with.
            fall_rect: The bounding rect of the falling-notes area.
        """
        minor: QColor = QColor(Colors.BORDER.value.qcolor)
        minor.setAlpha(GRID_MINOR_ALPHA)
        major: QColor = QColor(Colors.BORDER.value.qcolor)
        major.setAlpha(GRID_MAJOR_ALPHA)
        painter.save()
        painter.setPen(QPen(minor, 1))
        for note in range(MIDI_NOTE_MIN, MIDI_NOTE_MAX + 1):
            if note % 12 == 0:
                x, _ = self.__key_geometry[note]
                painter.drawLine(QPointF(x, fall_rect.top()), QPointF(x, fall_rect.bottom()))
        pixels_per_second: float = fall_rect.height() / LOOKAHEAD_SECONDS
        steps_per_second: int = round(1 / GRID_STEP_SECONDS)
        first_step: int = math.ceil(self.__position / GRID_STEP_SECONDS)
        last_step: int = math.floor((self.__position + LOOKAHEAD_SECONDS) / GRID_STEP_SECONDS)
        for step in range(first_step, last_step + 1):
            y: float = (fall_rect.bottom()
                        - (step * GRID_STEP_SECONDS - self.__position) * pixels_per_second)
            painter.setPen(QPen(major if step % steps_per_second == 0 else minor, 1))
            painter.drawLine(QPointF(fall_rect.left(), y), QPointF(fall_rect.right(), y))
        painter.restore()

    def __telemetry_readouts(self, voices: int) -> tuple[tuple[str, str, Colors], ...]:
        """Return the HUD's live readouts as (label, value, category color) triples.

        Args:
            voices: How many distinct keys are sounding right now.

        Returns:
            The readouts, in display order.
        """
        recent: int = (bisect.bisect_right(self.__starts, self.__position)
                       - bisect.bisect_left(self.__starts,
                                            self.__position - DENSITY_WINDOW_SECONDS))
        minutes, seconds = divmod(max(0.0, self.__position), 60)
        return (
            ("VOICES", f"{voices:02d}", Colors.GREEN),
            ("NOTES/S", f"{recent / DENSITY_WINDOW_SECONDS:04.1f}", Colors.SOLO),
            ("TRACKS", f"{len(self.__tracks - self.__muted_tracks):02d}", Colors.MODE),
            ("T+", f"{int(minutes):02d}:{seconds:04.1f}", Colors.ACCENT_1),
        )

    def __draw_telemetry(self, painter: QPainter, fall_rect: QRectF, voices: int) -> None:
        """Draw the HUD's live readouts as a row of glass chips along the top of the fall area.

        Each chip gets a small glowing status dot in its category color, a
        muted technical label, and a monospaced value.

        Args:
            painter: The active painter to draw with.
            fall_rect: The bounding rect of the falling-notes area.
            voices: How many distinct keys are sounding right now.
        """
        painter.save()
        painter.setFont(self.__telemetry_font)
        metrics: QFontMetricsF = QFontMetricsF(self.__telemetry_font)
        height: float = metrics.height() + TELEMETRY_PADDING
        x: float = fall_rect.left() + TELEMETRY_MARGIN
        y: float = fall_rect.top() + TELEMETRY_MARGIN
        background: QColor = QColor(Colors.BACKGROUND_1.value.qcolor)
        background.setAlpha(TELEMETRY_CHIP_ALPHA)
        for label, value, color in self.__telemetry_readouts(voices):
            label_width: float = metrics.horizontalAdvance(label)
            value_width: float = metrics.horizontalAdvance(value)
            width: float = (TELEMETRY_PADDING * 2 + TELEMETRY_DOT_SIZE + TELEMETRY_SPACING
                            + label_width + TELEMETRY_SPACING / 2 + value_width)
            chip: QRectF = QRectF(x, y, width, height)
            painter.setPen(QPen(Colors.BORDER.value.qcolor, 1))
            painter.setBrush(background)
            painter.drawRoundedRect(chip, height / 2, height / 2)
            dot: QRectF = QRectF(x + TELEMETRY_PADDING, chip.center().y() - TELEMETRY_DOT_SIZE / 2,
                                 TELEMETRY_DOT_SIZE, TELEMETRY_DOT_SIZE)
            draw_glow(painter, dot, color.value.qcolor, TELEMETRY_DOT_SIZE / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color.value.qcolor)
            painter.drawEllipse(dot)
            text_x: float = dot.right() + TELEMETRY_SPACING
            painter.setPen(Colors.TEXT_MUTED.value.qcolor)
            painter.drawText(QRectF(text_x, y, label_width, height),
                             int(Qt.AlignmentFlag.AlignVCenter), label)
            painter.setPen(Colors.WHITE.value.qcolor)
            painter.drawText(QRectF(text_x + label_width + TELEMETRY_SPACING / 2, y,
                                    value_width, height),
                             int(Qt.AlignmentFlag.AlignVCenter), value)
            x += width + TELEMETRY_SPACING
        painter.restore()

    @override
    def paintEvent(self, _event: QPaintEvent) -> None:
        """Paint the falling-notes area and the piano keyboard.

        Args:
            _event: The Qt paint event; unused (paints based on internal state).
        """
        self.__ensure_key_geometry()
        skin: Skin = active_skin()
        painter: QPainter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Glass skins draw the visualizer as a rounded, bordered card like
        # every other panel; everything below is clipped to its shape.
        card: QPainterPath|None = None
        if skin.glass:
            card = QPainterPath()
            card.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                skin.radius_md, skin.radius_md)
            painter.setClipPath(card)
        background: QLinearGradient = QLinearGradient(0, 0, 0, self.height())
        background.setColorAt(0.0, QColor(Colors.BACKGROUND.value.hex))
        background.setColorAt(1.0, QColor(Colors.BACKGROUND_1.value.hex))
        painter.fillRect(self.rect(), QBrush(background))
        keyboard_height: float = self.height() * KEYBOARD_HEIGHT_RATIO
        fall_rect: QRectF = QRectF(0, 0, self.width(), self.height() - keyboard_height)
        keyboard_rect: QRectF = QRectF(0, fall_rect.bottom(), self.width(), keyboard_height)
        visible: list[NoteEvent] = self.__visible_events()
        sounding: dict[int, str] = self.__sounding_notes(visible)
        if skin.hud:
            self.__draw_grid(painter, fall_rect)
        self.__draw_falling_notes(painter, fall_rect, visible)
        self.__draw_hit_line(painter, fall_rect)
        self.__draw_keyboard(painter, keyboard_rect, sounding)
        if skin.hud:
            self.__draw_telemetry(painter, fall_rect, len(sounding))
        if card is not None:
            painter.setClipping(False)
            painter.setPen(QPen(Colors.BORDER.value.qcolor, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(card)
        painter.end()

if __name__ == "__main__":
    ...
