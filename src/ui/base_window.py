from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout


class BaseWindow(QMainWindow):
    """
    Plain main-window base for chrome'd dialogs (Settings, Main).

    Uses the native window frame (close / minimize / maximize buttons,
    drag-by-titlebar, etc.). The previous frameless + custom-paint design
    fought the system theme on Windows 11 and produced inconsistent
    rendering — replaced here with native chrome + a clean QSS theme
    applied at the QApplication level.

    The floating recording overlay (`StatusWindow`) intentionally opts
    out of this in its own `initUI`.
    """

    def __init__(self, title, width, height):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(width, height)

        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(24, 20, 24, 20)
        self.main_layout.setSpacing(14)
        self.setCentralWidget(self.main_widget)

        self._center_on_screen()

    def _center_on_screen(self):
        center = QGuiApplication.primaryScreen().availableGeometry().center()
        frame = self.frameGeometry()
        frame.moveCenter(center)
        self.move(frame.topLeft())
