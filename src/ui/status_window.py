import sys
import os
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QRectF
from PySide6.QtGui import QFont, QPixmap, QIcon, QPainter, QBrush, QColor, QPainterPath
from PySide6.QtWidgets import QApplication, QLabel, QHBoxLayout, QMainWindow, QWidget, QVBoxLayout

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import resource_path


class StatusWindow(QMainWindow):
    """
    Small frameless overlay shown while WhisperWriter is recording or
    transcribing. Pinned bottom-center, always-on-top, click-to-dismiss
    via close signal.

    Does NOT inherit BaseWindow because it intentionally keeps the old
    frameless + custom-paint look (which suits a transient overlay,
    even though it doesn't suit modal dialogs).
    """

    statusSignal = Signal(str)
    closeSignal = Signal()

    def __init__(self):
        super().__init__()
        self._init_ui()
        self.statusSignal.connect(self.updateStatus)

    def _init_ui(self):
        self.setWindowTitle('WhisperWriter Status')
        self.setFixedSize(260, 64)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 12, 16, 12)
        self.setCentralWidget(central)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(28, 28)
        self.microphone_pixmap = QPixmap(resource_path(os.path.join('assets', 'microphone.png'))).scaled(
            28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.pencil_pixmap = QPixmap(resource_path(os.path.join('assets', 'pencil.png'))).scaled(
            28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.icon_label.setPixmap(self.microphone_pixmap)
        self.icon_label.setAlignment(Qt.AlignCenter)

        self.status_label = QLabel('Recording…')
        self.status_label.setFont(QFont('Segoe UI Variable', 11))
        self.status_label.setStyleSheet('color: #1d1d1f;')

        row.addWidget(self.icon_label)
        row.addWidget(self.status_label, 1)
        outer.addLayout(row)

    def show(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = screen.height() - self.height() - 120
        self.move(x, y)
        super().show()

    def closeEvent(self, event):
        self.closeSignal.emit()
        super().closeEvent(event)

    @Slot(str)
    def updateStatus(self, status):
        if status == 'recording':
            self.icon_label.setPixmap(self.microphone_pixmap)
            self.status_label.setText('Recording…')
            self.show()
        elif status == 'transcribing':
            self.icon_label.setPixmap(self.pencil_pixmap)
            self.status_label.setText('Transcribing…')
        elif status in ('idle', 'error', 'cancel'):
            self.close()

    def paintEvent(self, event):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 16, 16)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(255, 255, 255, 240)))
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = StatusWindow()
    w.show()
    QTimer.singleShot(2000, lambda: w.statusSignal.emit('transcribing'))
    QTimer.singleShot(4000, lambda: w.statusSignal.emit('idle'))
    sys.exit(app.exec())
