"""Custom frameless-window title bar: icon, title, minimize, maximize, close."""

from typing import override

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QWidget

from ui.buttons.close import CloseButton
from ui.buttons.maximize import MaximizeButton
from ui.buttons.minimize import MinimizeButton
from utils.common import (
    SPACING_XS,
    TITLEBAR_HEIGHT,
    Colors,
    active_skin,
    heading_font_qss,
    theme_bus,
)

ICON_SIZE = QSize(16, 16)


class TitleBar(QWidget):
    """Draggable title bar replacing the native window frame's caption area."""

    def __init__(self, window: QMainWindow, title: str, icon: QIcon,
                 parent: QWidget|None=None) -> None:
        """Initialize the title bar for the given top-level window.

        Args:
            window: The top-level window this title bar controls.
            title: The window title text to display.
            icon: The window icon to display.
            parent: Optional parent widget.
        """
        super().__init__(parent=parent)
        self.__window: QMainWindow = window
        self.__normal_geometry: QRect|None = None
        self.setFixedHeight(TITLEBAR_HEIGHT)
        # Plain QWidget subclasses (unlike QFrame) don't paint a QSS
        # background-color at all unless this attribute is set - without it,
        # re-styling on a theme switch would silently no-op.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_XS * 2, 0, SPACING_XS, 0)
        layout.setSpacing(SPACING_XS)
        icon_label: QLabel = QLabel()
        icon_label.setPixmap(icon.pixmap(ICON_SIZE))
        icon_label.setStyleSheet("background: transparent;")
        self.__title_label: QLabel = QLabel(title)
        self.__maximize_button: MaximizeButton = MaximizeButton()
        layout.addWidget(icon_label)
        layout.addWidget(self.__title_label, stretch=1)
        layout.addWidget(MinimizeButton())
        layout.addWidget(self.__maximize_button)
        layout.addWidget(CloseButton())
        self.__wire_buttons(layout)
        self.__style()
        theme_bus.changed.connect(self.__style)

    def __style(self) -> None:
        """Apply theme-dependent colors to the bar background and title text."""
        # Glass skins let the window backdrop show through the chrome.
        background: str = "transparent" if active_skin().glass else Colors.BACKGROUND.value.hex
        self.setStyleSheet(f"background-color: {background};")
        self.__title_label.setStyleSheet(
            f"color: {Colors.WHITE.value.hex}; font-weight: bold; background: transparent; "
            f"{heading_font_qss()}")

    def __wire_buttons(self, layout: QHBoxLayout) -> None:
        """Connect the minimize/maximize/close buttons to the window.

        Args:
            layout: The layout the buttons were added to, used to look them
                up by position.
        """
        minimize_button: MinimizeButton = layout.itemAt(2).widget()
        close_button: CloseButton = layout.itemAt(4).widget()
        minimize_button.clicked.connect(self.__window.showMinimized)
        self.__maximize_button.clicked.connect(self.__toggle_maximize)
        close_button.clicked.connect(self.__window.close)

    def __toggle_maximize(self) -> None:
        """Toggle the window between maximized and normal.

        Frameless windows on Windows can flip their internal maximized state
        without Qt actually restoring the geometry on the first showNormal()
        call, so the correct geometry is re-asserted explicitly afterward
        rather than trusting showNormal() alone.
        """
        if self.__window.isMaximized():
            self.__window.showNormal()
            if self.__normal_geometry is not None:
                self.__window.setGeometry(self.__normal_geometry)
        else:
            self.__normal_geometry = self.__window.geometry()
            self.__window.showMaximized()

    def set_maximized(self, maximized: bool) -> None:
        """Reflect the window's actual maximized state on the maximize button.

        Args:
            maximized: Whether the window is currently maximized.
        """
        self.__maximize_button.set_maximized(maximized)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start an OS-native window move via QWindow.startSystemMove().

        Args:
            event: The Qt mouse press event.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.__window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Toggle maximize on double-click, matching standard OS title-bar behavior.

        Args:
            event: The Qt mouse double-click event.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.__toggle_maximize()
        super().mouseDoubleClickEvent(event)

if __name__ == "__main__":
    ...
