import os
import sys
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton, QHBoxLayout, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, Signal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from ui.base_window import BaseWindow


class MainWindow(BaseWindow):
    openSettings = Signal()
    startListening = Signal()
    closeApp = Signal()

    def __init__(self):
        super().__init__('WhisperWriter', 360, 220)
        self._init_main_ui()

    def _init_main_ui(self):
        title = QLabel('WhisperWriter')
        title.setFont(QFont('Segoe UI Variable', 18, QFont.DemiBold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('color: #1d1d1f;')

        subtitle = QLabel('Press your hotkey anywhere to dictate.')
        subtitle.setProperty('secondary', True)
        subtitle.setAlignment(Qt.AlignCenter)

        start_btn = QPushButton('Start listening')
        start_btn.setMinimumHeight(36)
        start_btn.setMinimumWidth(140)
        start_btn.setDefault(True)
        start_btn.clicked.connect(self._on_start)

        settings_btn = QPushButton('Settings')
        settings_btn.setProperty('secondary', True)
        settings_btn.setMinimumHeight(36)
        settings_btn.setMinimumWidth(140)
        settings_btn.clicked.connect(self.openSettings.emit)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch(1)
        button_row.addWidget(start_btn)
        button_row.addWidget(settings_btn)
        button_row.addStretch(1)

        self.main_layout.addStretch(1)
        self.main_layout.addWidget(title)
        self.main_layout.addWidget(subtitle)
        self.main_layout.addSpacing(8)
        self.main_layout.addLayout(button_row)
        self.main_layout.addStretch(1)

    def closeEvent(self, event):
        self.closeApp.emit()

    def _on_start(self):
        self.startListening.emit()
        self.hide()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
