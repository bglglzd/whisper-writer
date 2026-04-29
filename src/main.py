import os
import sys

# Redirect stdout/stderr to a log file. In a frozen bundle there's no console
# to print to; in source mode we usually launch via pythonw / start.vbs which
# also has no console. Truncated on each launch so the file always reflects
# the current session.
if hasattr(sys, '_MEIPASS'):
    _log_dir = os.path.dirname(sys.executable)
else:
    _log_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    _log_path = os.path.join(_log_dir, 'whisper-writer.log')
    _log_file = open(_log_path, 'w', encoding='utf-8', buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file
except Exception:
    pass

# Add NVIDIA CUDA DLL directories to PATH and DLL search directories before
# any CUDA imports. We check three locations:
#   - sys._MEIPASS / nvidia / ...        (frozen CUDA bundle)
#   - sys.prefix / Lib / site-packages   (system / venv install)
#   - <project root>/venv/Lib/site-packages   (source mode)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cuda_search_bases = []
if hasattr(sys, '_MEIPASS'):
    _cuda_search_bases.append(sys._MEIPASS)
_cuda_search_bases.append(os.path.join(sys.prefix, 'Lib', 'site-packages'))
_cuda_search_bases.append(os.path.join(_project_root, 'venv', 'Lib', 'site-packages'))
for _base in _cuda_search_bases:
    for _nvidia_sub in ('nvidia\\cublas\\bin', 'nvidia\\cudnn\\bin'):
        _dll_path = os.path.abspath(os.path.join(_base, _nvidia_sub))
        if os.path.isdir(_dll_path):
            os.environ['PATH'] = _dll_path + os.pathsep + os.environ.get('PATH', '')
            if hasattr(os, 'add_dll_directory'):
                os.add_dll_directory(_dll_path)

# IMPORTANT: Load CUDA model BEFORE importing Qt to avoid segfault
from utils import ConfigManager, resource_path
from transcription import create_local_model

_preloaded_model = None
if __name__ == '__main__':
    ConfigManager.initialize()
    model_options = ConfigManager.get_config_section('model_options')
    if not model_options.get('use_api'):
        print('Pre-loading Whisper model (before Qt)...')
        _preloaded_model = create_local_model()
        print('Model loaded.')

import soundfile as sf
import sounddevice as sd
from pynput.keyboard import Controller
from PySide6.QtCore import QObject, QProcess
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

GLOBAL_QSS = """
/* ---------- Apple-ish light theme ---------- */
QMainWindow, QDialog, QMessageBox {
    background-color: #f5f5f7;
}

QWidget {
    color: #1d1d1f;
    font-family: "Segoe UI Variable", "Segoe UI", "SF Pro Text", sans-serif;
    font-size: 10pt;
}

/* Form labels and helper text */
QLabel {
    color: #1d1d1f;
    background: transparent;
}
QLabel[secondary="true"] {
    color: #6e6e73;
    font-size: 9pt;
}
QLabel[section_header="true"] {
    color: #6e6e73;
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 1px;
    padding-top: 6px;
    padding-bottom: 2px;
}

QFrame[separator="true"] {
    color: #d2d2d7;
    background-color: #d2d2d7;
    max-height: 1px;
    border: none;
}

/* Tab bar — segmented-control feel */
QTabWidget::pane {
    border: 1px solid #d2d2d7;
    border-radius: 10px;
    background: #ffffff;
    top: -1px;
}
QTabBar {
    qproperty-drawBase: 0;
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: #6e6e73;
    padding: 8px 18px;
    border: 1px solid transparent;
    margin: 0 2px;
    min-width: 80px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1d1d1f;
    border: 1px solid #d2d2d7;
    border-bottom: 1px solid #ffffff;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:hover:!selected {
    color: #1d1d1f;
}

/* Primary buttons (Apple system blue) */
QPushButton {
    background-color: #0071e3;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
    min-height: 24px;
}
QPushButton:hover { background-color: #0077ed; }
QPushButton:pressed { background-color: #006edb; }
QPushButton:disabled { background-color: #aeaeb2; color: #f5f5f7; }
QPushButton:default { background-color: #0071e3; }

/* Secondary buttons (Discard, Browse, Settings) */
QPushButton[secondary="true"] {
    background-color: #ffffff;
    color: #1d1d1f;
    border: 1px solid #d2d2d7;
}
QPushButton[secondary="true"]:hover {
    background-color: #fafafa;
    border-color: #c0c0c5;
}
QPushButton[secondary="true"]:pressed {
    background-color: #f0f0f2;
}

/* Inputs */
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 6px;
    padding: 5px 9px;
    color: #1d1d1f;
    min-height: 22px;
    selection-background-color: #0071e3;
    selection-color: white;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #0071e3;
}
QLineEdit:disabled, QComboBox:disabled {
    background-color: #f5f5f7;
    color: #8e8e93;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 6px;
    selection-background-color: #0071e3;
    selection-color: #ffffff;
    padding: 4px 0;
}

/* Checkboxes — keep native indicator (Fusion paints a clean one) */
QCheckBox {
    spacing: 8px;
    color: #1d1d1f;
}

/* Help / icon-only buttons in form rows */
QToolButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}
QToolButton:hover {
    background-color: #ebebed;
}

/* Tooltips */
QToolTip {
    background-color: #1d1d1f;
    color: #ffffff;
    border: none;
    padding: 6px 10px;
    border-radius: 6px;
}
"""

from key_listener import KeyListener
from result_thread import ResultThread
from ui.main_window import MainWindow
from ui.settings_window import SettingsWindow
from ui.status_window import StatusWindow
from input_simulation import InputSimulator


class WhisperWriterApp(QObject):
    def __init__(self, preloaded_model=None):
        """
        Initialize the application, opening settings window if no configuration file is found.
        """
        super().__init__()
        self.preloaded_model = preloaded_model
        self.app = QApplication(sys.argv)
        self.app.setStyle('Fusion')
        self.app.setStyleSheet(GLOBAL_QSS)
        self.app.setWindowIcon(QIcon(resource_path(os.path.join('assets', 'ww-logo.png'))))

        ConfigManager.initialize()

        self.settings_window = SettingsWindow()
        self.settings_window.settings_closed.connect(self.on_settings_closed)
        self.settings_window.settings_saved.connect(self.restart_app)

        if ConfigManager.config_file_exists():
            self.initialize_components()
        else:
            print('No valid configuration file found. Opening settings window...')
            self.settings_window.show()

    def initialize_components(self):
        """
        Initialize the components of the application.
        """
        self.input_simulator = InputSimulator()

        self.key_listener = KeyListener()
        self.key_listener.add_callback("on_activate", self.on_activation)
        self.key_listener.add_callback("on_deactivate", self.on_deactivation)

        model_options = ConfigManager.get_config_section('model_options')
        if self.preloaded_model:
            self.local_model = self.preloaded_model
        else:
            self.local_model = create_local_model() if not model_options.get('use_api') else None

        self.result_thread = None

        self.main_window = MainWindow()
        self.main_window.openSettings.connect(self.settings_window.show)
        self.main_window.startListening.connect(self.key_listener.start)
        self.main_window.closeApp.connect(self.exit_app)

        if not ConfigManager.get_config_value('misc', 'hide_status_window'):
            self.status_window = StatusWindow()

        self.create_tray_icon()
        self.main_window.show()

    def create_tray_icon(self):
        """
        Create the system tray icon and its context menu.
        """
        self.tray_icon = QSystemTrayIcon(QIcon(resource_path(os.path.join('assets', 'ww-logo.png'))), self.app)

        tray_menu = QMenu()

        show_action = QAction('WhisperWriter Main Menu', self.app)
        show_action.triggered.connect(self.main_window.show)
        tray_menu.addAction(show_action)

        settings_action = QAction('Open Settings', self.app)
        settings_action.triggered.connect(self.settings_window.show)
        tray_menu.addAction(settings_action)

        exit_action = QAction('Exit', self.app)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def cleanup(self):
        self._cleanup_result_thread()
        if self.key_listener:
            self.key_listener.stop()
        if self.input_simulator:
            self.input_simulator.cleanup()

    def exit_app(self):
        """
        Exit the application.
        """
        self.cleanup()
        QApplication.quit()

    def restart_app(self):
        """Restart the application to apply the new settings."""
        self.cleanup()
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    def on_settings_closed(self):
        """
        If settings is closed without saving on first run, initialize the components with default values.
        """
        if not ConfigManager.config_file_exists():
            QMessageBox.information(
                self.settings_window,
                'Using Default Values',
                'Settings closed without saving. Default values are being used.'
            )
            self.initialize_components()

    def on_activation(self):
        """
        Called when the activation key combination is pressed.

        First press starts recording. Second press stops recording and
        triggers transcription — whether the recording mode is
        `press_to_toggle` or `continuous`. (The original `continuous`
        path called `stop_result_thread()`, which discarded the audio
        instead of transcribing it.)
        """
        ConfigManager.console_print('Hotkey pressed')
        if self.result_thread and self.result_thread.isRunning():
            self.result_thread.stop_recording()
            return
        self.start_result_thread()

    def on_deactivation(self):
        """
        Called when the activation key combination is released.
        """
        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'hold_to_record':
            if self.result_thread and self.result_thread.isRunning():
                self.result_thread.stop_recording()

    def _cleanup_result_thread(self):
        """Clean up the previous result thread to prevent thread/memory leaks."""
        if self.result_thread is not None:
            if self.result_thread.isRunning():
                self.result_thread.stop()
            self.result_thread.statusSignal.disconnect()
            self.result_thread.resultSignal.disconnect()
            if not ConfigManager.get_config_value('misc', 'hide_status_window'):
                self.status_window.closeSignal.disconnect(self.stop_result_thread)
            self.result_thread.deleteLater()
            self.result_thread = None

    def start_result_thread(self):
        """
        Start the result thread to record audio and transcribe it.
        """
        if self.result_thread and self.result_thread.isRunning():
            return

        self._cleanup_result_thread()

        self.result_thread = ResultThread(self.local_model)
        if not ConfigManager.get_config_value('misc', 'hide_status_window'):
            self.result_thread.statusSignal.connect(self.status_window.updateStatus)
            self.status_window.closeSignal.connect(self.stop_result_thread)
        self.result_thread.resultSignal.connect(self.on_transcription_complete)
        self.result_thread.start()

    def stop_result_thread(self):
        """
        Stop the result thread.
        """
        if self.result_thread and self.result_thread.isRunning():
            self.result_thread.stop()

    def _play_completion_beep(self):
        """Play the completion beep using sounddevice (already a dep, no extra install)."""
        try:
            data, sample_rate = sf.read(resource_path(os.path.join('assets', 'beep.wav')))
            sd.play(data, sample_rate)
            sd.wait()
        except Exception as e:
            ConfigManager.console_print(f'Could not play completion beep: {e}')

    def on_transcription_complete(self, result):
        """
        When the transcription is complete, type the result and start listening for the activation key again.
        """
        injected = self.input_simulator.typewrite(result)
        if not injected and result:
            # Every synthetic-input path was blocked (security software with
            # a low-level keyboard hook, etc.). The text is still on the
            # clipboard — tell the user via a tray balloon so they know
            # to paste manually with Ctrl+V.
            try:
                self.tray_icon.showMessage(
                    'WhisperWriter — text copied',
                    'Synthetic input blocked. Press Ctrl+V to paste.',
                    QSystemTrayIcon.Information,
                    4000,
                )
            except Exception:
                pass

        if ConfigManager.get_config_value('misc', 'noise_on_completion'):
            self._play_completion_beep()

        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'continuous':
            self.start_result_thread()
        else:
            self.key_listener.start()

    def run(self):
        """
        Start the application.
        """
        sys.exit(self.app.exec())


if __name__ == '__main__':
    app = WhisperWriterApp(preloaded_model=_preloaded_model)
    app.run()
