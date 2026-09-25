"""Settings dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QWidget,
)

from ui.combo_box import ComboBox
from ui.dialog_style import apply_dialog_theme
from ui.key_configurator import KeyConfigurator
from ui.toggle_switch import ToggleSwitch
from utils.common import (
    active_skin,
    apply_skin,
    apply_theme,
    current_skin_name,
    current_theme,
    theme_bus,
)
from utils.skins import SKINS


class SettingsDialog(QDialog):
    """Simple Settings selection Dialog."""

    def __init__(self, parent: QWidget|None=None) -> None:
        """Initialize the Settings dialog.

        Args:
            parent: Optional parent widget; also supplies the window icon.
        """
        super().__init__(parent)
        if parent:
            self.setWindowIcon(parent.windowIcon())
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.__theme_label: QLabel
        self.__theme_row: QWidget
        apply_dialog_theme(self)
        theme_bus.changed.connect(lambda: apply_dialog_theme(self))
        self.__create_layout()

    def __open_key_configurator_on_click(self) -> None:
        """Open the KeyConfigurator dialog modally."""
        dialog: KeyConfigurator = KeyConfigurator(self)
        dialog.exec()

    def __construct_key_binding_section(self, layout: QGridLayout, row: int) -> int:
        """Add the "Configure keybindings" row.

        Args:
            layout: The grid layout to add the row to.
            row: The next free row index in layout.

        Returns:
            The next free row index after the added row.
        """
        button: QPushButton = QPushButton()
        button.setText("Open")
        button.clicked.connect(self.__open_key_configurator_on_click)
        layout.addWidget(QLabel("Configure keybindings"), row, 0, 1, 1,
                         alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(button, row, 1, 1, 1)
        return row + 1

    def __construct_skin_section(self, layout: QGridLayout, row: int) -> int:
        """Add the "Skin" row with a picker listing every registered skin.

        Args:
            layout: The grid layout to add the row to.
            row: The next free row index in layout.

        Returns:
            The next free row index after the added row.
        """
        combo: ComboBox = ComboBox()
        for name, skin in SKINS.items():
            combo.addItem(skin.display_name, name)
        combo.setCurrentIndex(combo.findData(current_skin_name()))
        combo.currentIndexChanged.connect(lambda index: apply_skin(combo.itemData(index)))
        layout.addWidget(QLabel("Skin"), row, 0, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(combo, row, 1, 1, 1)
        return row + 1

    def __construct_theme_section(self, layout: QGridLayout, row: int) -> int:
        """Add the "Theme" row with a Dark/Light toggle.

        Disabled while the active skin only supports one variant (e.g.
        Cyberpunk is dark-only); the toggle still shows the user's saved
        preference, which applies again once they pick a skin that has it.

        Args:
            layout: The grid layout to add the row to.
            row: The next free row index in layout.

        Returns:
            The next free row index after the added row.
        """
        toggle: ToggleSwitch = ToggleSwitch()
        toggle.setChecked(current_theme() == "light")
        toggle.toggled.connect(lambda checked: apply_theme("light" if checked else "dark"))
        self.__theme_row = QWidget()
        row_layout: QHBoxLayout = QHBoxLayout(self.__theme_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(QLabel("Dark"))
        row_layout.addWidget(toggle)
        row_layout.addWidget(QLabel("Light"))
        self.__theme_label = QLabel("Theme")
        layout.addWidget(self.__theme_label, row, 0, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.__theme_row, row, 1, 1, 1)
        self.__sync_theme_enabled()
        return row + 1

    def __sync_theme_enabled(self) -> None:
        """Enable the Dark/Light row only if the active skin has more than one variant."""
        enabled: bool = len(active_skin().variants) > 1
        self.__theme_label.setEnabled(enabled)
        self.__theme_row.setEnabled(enabled)

    def __create_layout(self) -> None:
        """Create the dialog's full layout."""
        layout: QGridLayout = QGridLayout()
        # Size to content and stay non-resizable, re-fitting automatically if
        # a skin's font changes the content's size.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        row: int = 0
        row = self.__construct_key_binding_section(layout, row)
        row = self.__construct_skin_section(layout, row)
        row = self.__construct_theme_section(layout, row)
        self.setLayout(layout)
        theme_bus.changed.connect(self.__sync_theme_enabled)

if __name__ == "__main__":
    ...
