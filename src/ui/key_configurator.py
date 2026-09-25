"""Key Configurator dialog."""

import re
from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ui.buttons.key import KeyButton
from ui.dialog_style import apply_dialog_theme
from ui.key_catcher import KeyCatcher
from utils.common import Colors, active_skin, theme_bus
from utils.wwm_macro import KeyManager


class KeyConfigurator(QDialog):
    """Key Configurator Dialog."""

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize Key Configurator.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Key Configurator")
        self.setModal(True)
        apply_dialog_theme(self)
        theme_bus.changed.connect(lambda: apply_dialog_theme(self))
        self.__manager: KeyManager = KeyManager()
        self.__buttons: list[KeyButton] = []
        self.__create_layout()

    @Slot()
    def __reset_on_click(self) -> None:
        """Restore every key button's label and the saved bindings to defaults."""
        default_bindings: dict[str, Any] = self.__manager.default_bindings
        for button in self.__buttons:
            button.setText(default_bindings[button.octave][button.note])
        self.__manager.reset_keybindings()

    def __key_button_on_click(self, button: KeyButton) -> None:
        """Open KeyCatcher to rebind a note and persist the chosen key.

        Args:
            button: The key button that was clicked.
        """
        forbidden_keys: list[str] = [button.text() for button in self.__buttons]
        forbidden_keys.remove(button.text())
        dialog: KeyCatcher = KeyCatcher(forbidden_keys, parent=self)
        dialog.exec()
        pressed_key: str = dialog.key
        if not pressed_key:
            return
        button.setText(pressed_key)
        self.__manager.update_keybinding(button.octave, button.note, pressed_key)

    def __construct_key_button(self, layout: QHBoxLayout, octave: str, note: str, key: str) -> None:
        """Create one KeyButton, track it, and add it to layout.

        Args:
            layout: The row layout to add the button to.
            octave: The register this key belongs to ("low", "med", "high").
            note: The scale degree this key is bound to (e.g. "1", "#4").
            key: The currently bound key label to display.
        """
        button: KeyButton = KeyButton(key, octave=octave, note=note)
        button.clicked.connect(lambda: self.__key_button_on_click(button))
        self.__buttons.append(button)
        layout.addWidget(button)

    def __construct_key_binding_section(self, layout: QGridLayout, row: int) -> int:
        """Add one grouped row of key buttons per octave register.

        Args:
            layout: The grid layout to add rows to.
            row: The next free row index in layout.

        Returns:
            The next free row index after the added rows.
        """
        for octave, notes in self.__manager.bindings.items():
            group: QGroupBox = QGroupBox(f"{octave.title()} Octave")
            radius: int = active_skin().radius_sm
            group.setStyleSheet(f"""
                QGroupBox {{
                    background-color: {Colors.BACKGROUND_1.value.hex};
                    border: none;
                    border-radius: {radius}px;
                    margin-top: 10px;
                    padding: 10px;
                }}
                QGroupBox::title {{
                    background-color: {Colors.BACKGROUND_1.value.hex};
                    border-radius: {radius}px;
                    subcontrol-origin: margin;
                    subcontrol-position: top center;
                    padding: 4px 8px;
                }}
            """)
            group_layout: QHBoxLayout = QHBoxLayout(group)
            for note, key in notes.items():
                if re.search(r"#|b", note):
                    continue
                self.__construct_key_button(group_layout, octave, note, key)
            layout.addWidget(group, row, 0, 1, -1)
            row += 1
        return row + 1

    def __create_layout(self) -> None:
        """Create the dialog's full layout."""
        layout: QGridLayout = QGridLayout()
        row: int = 0
        header: QLabel = QLabel("Customize which keys play each note. Click a key to change it.")
        header.setStyleSheet(
            "font-size: 14pt; font-weight: bold; padding-bottom: 8px; background: transparent;")
        layout.addWidget(header, row, 0, 1, -1, alignment=Qt.AlignmentFlag.AlignCenter)
        row += 1
        row = self.__construct_key_binding_section(layout, row)
        button: QPushButton = QPushButton("Reset")
        button.clicked.connect(self.__reset_on_click)
        layout.addWidget(button, row, 0, 1, -1, alignment=Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)
        self.adjustSize()
        self.setFixedSize(self.size())

if __name__ == "__main__":
    ...
