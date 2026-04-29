import os
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox
)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import cuda_installer


class _InstallWorker(QThread):
    """Runs `cuda_installer.install()` off the GUI thread."""

    stage_changed = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def run(self):
        try:
            cuda_installer.install(
                stage_cb=lambda msg: self.stage_changed.emit(msg),
                progress_cb=lambda d, t: self.progress.emit(d, t),
            )
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


class CudaInstallDialog(QDialog):
    """Modal dialog that downloads NVIDIA cuBLAS + cuDNN to the bundle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Install GPU support')
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.heading = QLabel('Enable NVIDIA GPU acceleration')
        self.heading.setStyleSheet('font-size: 12pt; font-weight: 600; color: #1d1d1f;')
        layout.addWidget(self.heading)

        self.body = QLabel(
            'WhisperWriter will download cuBLAS and cuDNN (~1.0 GB) from PyPI '
            'and unpack them into the install directory. Transcription '
            'will use your NVIDIA GPU after the next restart.'
        )
        self.body.setWordWrap(True)
        self.body.setProperty('secondary', True)
        layout.addWidget(self.body)

        self.stage_label = QLabel('')
        self.stage_label.setWordWrap(True)
        self.stage_label.setVisible(False)
        layout.addWidget(self.stage_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        layout.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setProperty('secondary', True)
        self.cancel_btn.clicked.connect(self.reject)
        self.install_btn = QPushButton('Install')
        self.install_btn.setDefault(True)
        self.install_btn.clicked.connect(self._start)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.install_btn)
        layout.addLayout(row)

        self.worker = None

    def _start(self):
        self.install_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.stage_label.setVisible(True)
        self.progress.setVisible(True)
        self.stage_label.setText('Starting…')
        self.worker = _InstallWorker(self)
        self.worker.stage_changed.connect(self.stage_label.setText)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, done, total):
        if total > 0:
            pct = int(done * 100 / total)
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)
            mb_done = done / 1024 / 1024
            mb_total = total / 1024 / 1024
            self.progress.setFormat(f'%p%  ({mb_done:.0f} / {mb_total:.0f} MB)')
        else:
            self.progress.setRange(0, 0)  # indeterminate
            self.progress.setFormat('Working…')

    def _on_done(self):
        self.stage_label.setText('GPU support installed. Restart WhisperWriter to use it.')
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat('Done')
        self.cancel_btn.setText('Close')
        self.cancel_btn.setEnabled(True)
        self.install_btn.setEnabled(False)

    def _on_failed(self, error):
        self.stage_label.setText('Installation failed.')
        QMessageBox.critical(
            self, 'Installation failed',
            f'Could not install GPU support:\n\n{error}\n\n'
            'Check your internet connection and try again, or run from source instead.',
        )
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText('Close')
        self.install_btn.setEnabled(True)
        self.install_btn.setText('Retry')
