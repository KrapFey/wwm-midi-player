"""Shared theme-aware QSS for QDialog-based windows."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from utils.common import Colors, active_skin, window_background_qss


def apply_dialog_theme(dialog: QWidget) -> None:
    """Apply the app's active palette to a dialog and its common child widgets.

    Args:
        dialog: The dialog widget to style.
    """
    # QDialog (like any plain QWidget) doesn't paint a QSS background-color
    # at all without this attribute - without it, a theme switch would
    # silently no-op and the dialog would keep showing Qt's default palette.
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    radius: int = active_skin().radius_sm
    dialog.setStyleSheet(f"""
        QDialog {{
            {window_background_qss()}
        }}
        QLabel {{
            color: {Colors.WHITE.value.hex};
        }}
        QLabel:disabled {{
            color: {Colors.TEXT_MUTED.value.hex};
        }}
        QGroupBox {{
            color: {Colors.WHITE.value.hex};
        }}
        QPushButton {{
            background-color: {Colors.BACKGROUND_1.value.hex};
            color: {Colors.WHITE.value.hex};
            border: 1px solid {Colors.BACKGROUND_2.value.hex};
            border-radius: {radius}px;
            padding: 6px 16px;
        }}
        QPushButton:hover {{
            background-color: {Colors.BACKGROUND_2.value.hex};
        }}
        QPushButton:pressed {{
            background-color: {Colors.ACCENT_1.value.hex};
        }}
        QPushButton:disabled {{
            color: {Colors.TEXT_MUTED.value.hex};
            border-color: {Colors.BACKGROUND_1.value.hex};
        }}
        QComboBox {{
            background-color: {Colors.BACKGROUND_1.value.hex};
            color: {Colors.WHITE.value.hex};
            border: 1px solid {Colors.BACKGROUND_2.value.hex};
            border-radius: {radius}px;
            padding: 5px 12px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        /* ui.combo_box.ComboBox paints its own palette-colored chevron. */
        QComboBox::down-arrow {{
            image: none;
        }}
        QComboBox:hover, QComboBox:focus {{
            border-color: {Colors.ACCENT_1.value.hex};
        }}
        QComboBox QAbstractItemView {{
            background-color: {Colors.BACKGROUND_1.value.hex};
            color: {Colors.WHITE.value.hex};
            border: 1px solid {Colors.BACKGROUND_2.value.hex};
            selection-background-color: {Colors.ACCENT_1.value.hex};
            outline: 0;
        }}
    """)
