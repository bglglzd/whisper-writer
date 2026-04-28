import os
import sys

# Add NVIDIA CUDA DLLs to PATH and DLL directories before any CUDA imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for nvidia_lib in ['nvidia\\cublas\\bin', 'nvidia\\cudnn\\bin']:
    for base in [os.path.join(sys.prefix, 'Lib', 'site-packages'),
                 os.path.join(_project_root, 'venv', 'Lib', 'site-packages')]:
        dll_path = os.path.abspath(os.path.join(base, nvidia_lib))
        if os.path.isdir(dll_path):
            os.environ['PATH'] = dll_path + os.pathsep + os.environ.get('PATH', '')
            if hasattr(os, 'add_dll_directory'):
                os.add_dll_directory(dll_path)

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
QPushButton {
    background-color: #4a90e2;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 22px;
}
QPushButton:hover { background-color: #5aa0f2; }
QPushButton:pressed { background-color: #3a80d2; }
QPushButton:disabled { background-color: #b0b0b0; color: #f0f0f0; }
QLineEdit, QComboBox {
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 4px 8px;
    background-color: white;
    min-height: 18px;
}
QLineEdit:focus, QComboBox:focus { border-color: #4a90e2; }
QCheckBox { spacing: 8px; }
QTabBar::tab {
    padding: 6px 14px;
    border: 1px solid #d0d0d0;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    background-color: #ececec;
}
QTabBar::tab:selected { background-color: white; }
QTabBar::tab:hover { background-color: #f5f5f5; }
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
        """
        if self.result_thread and self.result_thread.isRunning():
            recording_mode = ConfigManager.get_config_value('recording_options', 'recording_mode')
            if recording_mode == 'press_to_toggle':
                self.result_thread.stop_recording()
            elif recording_mode == 'continuous':
                self.stop_result_thread()
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
        self.input_simulator.typewrite(result)

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
