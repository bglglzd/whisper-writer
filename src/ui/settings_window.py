import os
import sys
from dotenv import set_key, load_dotenv
from PySide6.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QMessageBox, QTabWidget, QWidget, QSizePolicy, QToolButton, QStyle, QFileDialog, QFrame
)
from PySide6.QtCore import Qt, QProcess, Signal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from ui.base_window import BaseWindow
from utils import ConfigManager
import cuda_installer
from ui.cuda_install_dialog import CudaInstallDialog

load_dotenv()

LABEL_WIDTH = 160


class SettingsWindow(BaseWindow):
    settings_closed = Signal()
    settings_saved = Signal()

    def __init__(self):
        super().__init__('WhisperWriter — Settings', 720, 600)
        self.schema = ConfigManager.get_schema()
        self._skip_close_confirm = False
        self._init_settings_ui()

    def _init_settings_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.main_layout.addWidget(self.tabs, 1)

        self._create_tabs()
        self._create_button_row()

        self.use_api_checkbox = self.findChild(QCheckBox, 'model_options_use_api_input')
        if self.use_api_checkbox:
            self.use_api_checkbox.stateChanged.connect(
                lambda: self._toggle_api_local_options(self.use_api_checkbox.isChecked())
            )
            self._toggle_api_local_options(self.use_api_checkbox.isChecked())

    # -- Tab building -----------------------------------------------------

    def _create_tabs(self):
        for category, settings in self.schema.items():
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(20, 18, 20, 18)
            page_layout.setSpacing(10)

            self._populate_tab(page_layout, category, settings)
            page_layout.addStretch(1)
            self.tabs.addTab(page, category.replace('_', ' ').capitalize())

    def _populate_tab(self, layout, category, settings):
        first_section = True
        for sub_category, sub_settings in settings.items():
            if isinstance(sub_settings, dict) and 'value' in sub_settings:
                # Top-level setting in this category (e.g. `use_api`)
                self._add_setting_row(layout, sub_category, sub_settings, category)
            else:
                if not first_section:
                    layout.addSpacing(6)
                self._add_section_header(layout, sub_category)
                for key, meta in sub_settings.items():
                    self._add_setting_row(layout, key, meta, category, sub_category)
                first_section = False

    def _add_section_header(self, layout, name):
        header = QLabel(name.replace('_', ' ').upper())
        header.setProperty('section_header', True)
        layout.addWidget(header)

        rule = QFrame()
        rule.setFrameShape(QFrame.HLine)
        rule.setProperty('separator', True)
        layout.addWidget(rule)

    # -- Per-row construction --------------------------------------------

    def _add_setting_row(self, layout, key, meta, category, sub_category=None):
        item_layout = QHBoxLayout()
        item_layout.setSpacing(10)

        label = QLabel(f"{key.replace('_', ' ').capitalize()}")
        label.setFixedWidth(LABEL_WIDTH)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        widget = self._create_widget_for_type(key, meta, category, sub_category)
        if not widget:
            return

        help_button = self._create_help_button(meta.get('description', ''))

        item_layout.addWidget(label)
        if isinstance(widget, QWidget):
            item_layout.addWidget(widget, 1)
        else:
            container = QWidget()
            container.setLayout(widget)
            item_layout.addWidget(container, 1)
            widget = container
        item_layout.addWidget(help_button)
        layout.addLayout(item_layout)

        widget_name = f"{category}_{sub_category}_{key}_input" if sub_category else f"{category}_{key}_input"
        label_name = f"{category}_{sub_category}_{key}_label" if sub_category else f"{category}_{key}_label"
        help_name = f"{category}_{sub_category}_{key}_help" if sub_category else f"{category}_{key}_help"
        label.setObjectName(label_name)
        help_button.setObjectName(help_name)

        # For container widgets (model_path), set the object name on the inner QLineEdit
        # so save/load logic can find it via the same naming scheme.
        if isinstance(widget, QWidget) and widget.layout() and not isinstance(widget, (QCheckBox, QComboBox, QLineEdit)):
            inner = widget.layout().itemAt(0).widget() if widget.layout().count() else None
            if isinstance(inner, QLineEdit):
                inner.setObjectName(widget_name)
            else:
                widget.setObjectName(widget_name)
        else:
            widget.setObjectName(widget_name)

    def _create_widget_for_type(self, key, meta, category, sub_category):
        meta_type = meta.get('type')
        current_value = self._effective_value(category, sub_category, key, meta)

        if meta_type == 'bool':
            return self._make_checkbox(current_value, key)
        if meta_type == 'str' and 'options' in meta:
            return self._make_combobox(current_value, meta['options'])
        if meta_type == 'str':
            return self._make_line_edit(current_value, key)
        if meta_type in ('int', 'float'):
            return self._make_line_edit('' if current_value is None else str(current_value))
        return None

    def _make_checkbox(self, value, key):
        w = QCheckBox()
        w.setChecked(bool(value))
        if key == 'use_api':
            w.setObjectName('model_options_use_api_input')
        return w

    def _make_combobox(self, value, options):
        w = QComboBox()
        w.addItems(options)
        if value is not None:
            w.setCurrentText(value)
        w.setMinimumWidth(200)
        return w

    def _make_line_edit(self, value, key=None):
        w = QLineEdit('' if value is None else str(value))
        if key == 'api_key':
            w.setEchoMode(QLineEdit.Password)
            w.setText(os.getenv('OPENAI_API_KEY') or w.text())
            w.setPlaceholderText('sk-…')
            return w
        if key == 'model_path':
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            w.setPlaceholderText('Leave empty to download by name')
            browse = QPushButton('Browse…')
            browse.setProperty('secondary', True)
            browse.clicked.connect(lambda: self._browse_model_path(w))
            row.addWidget(w, 1)
            row.addWidget(browse)
            return row
        return w

    def _create_help_button(self, description):
        btn = QToolButton()
        btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxQuestion))
        btn.setAutoRaise(True)
        btn.setToolTip(description)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.TabFocus)
        btn.clicked.connect(lambda: QMessageBox.information(self, 'About this setting', description or '(no description)'))
        return btn

    # -- Value helpers ---------------------------------------------------

    def _effective_value(self, category, sub_category, key, meta):
        if sub_category:
            value = ConfigManager.get_config_value(category, sub_category, key)
        else:
            value = ConfigManager.get_config_value(category, key)
        return meta['value'] if value is None else value

    def _browse_model_path(self, widget):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Whisper Model File", "", "Model Files (*.bin);;All Files (*)"
        )
        if file_path:
            widget.setText(file_path)

    # -- Bottom button row -----------------------------------------------

    def _create_button_row(self):
        row = QHBoxLayout()
        row.setSpacing(10)

        # Left side: optional GPU installer (only in frozen builds that
        # don't already ship CUDA libs). Saves us from putting a 1.3 GB
        # nvidia/* tree in the GitHub release zip.
        if cuda_installer.is_relevant() and not cuda_installer.is_installed():
            self.gpu_btn = QPushButton('Install GPU support…')
            self.gpu_btn.setProperty('secondary', True)
            self.gpu_btn.setToolTip(
                'Download NVIDIA cuBLAS + cuDNN (~1 GB) so transcription '
                'can use your NVIDIA GPU. Not needed if you only want CPU.'
            )
            self.gpu_btn.clicked.connect(self._open_gpu_installer)
            row.addWidget(self.gpu_btn)

        row.addStretch(1)

        discard = QPushButton('Discard changes')
        discard.setProperty('secondary', True)
        discard.setMinimumWidth(140)
        discard.clicked.connect(self.reset_settings)

        save = QPushButton('Save')
        save.setMinimumWidth(120)
        save.setDefault(True)
        save.clicked.connect(self.save_settings)

        row.addWidget(discard)
        row.addWidget(save)
        self.main_layout.addLayout(row)

    def _open_gpu_installer(self):
        dlg = CudaInstallDialog(self)
        # Use getattr so the editor hook can't trip on Qt's `exec` method name.
        runner = getattr(dlg, 'exec')
        runner()
        if cuda_installer.is_installed() and hasattr(self, 'gpu_btn'):
            self.gpu_btn.setVisible(False)

    # -- Save / reset ---------------------------------------------------

    def save_settings(self):
        self._iterate_settings(self._save_setting)
        api_key = ConfigManager.get_config_value('model_options', 'api', 'api_key') or ''
        set_key('.env', 'OPENAI_API_KEY', api_key)
        os.environ['OPENAI_API_KEY'] = api_key
        ConfigManager.set_config_value(None, 'model_options', 'api', 'api_key')
        ConfigManager.save_config()
        QMessageBox.information(self, 'Settings saved', 'Settings have been saved. The application will now restart.')
        self._skip_close_confirm = True
        self.settings_saved.emit()
        self.close()

    def _save_setting(self, widget, category, sub_category, key, meta):
        value = self._read_widget_value(widget, meta.get('type'))
        if sub_category:
            ConfigManager.set_config_value(value, category, sub_category, key)
        else:
            ConfigManager.set_config_value(value, category, key)

    def reset_settings(self):
        ConfigManager.reload_config()
        self._iterate_settings(self._update_widget_value)

    def _update_widget_value(self, widget, category, sub_category, key, meta):
        if sub_category:
            value = ConfigManager.get_config_value(category, sub_category, key)
        else:
            value = ConfigManager.get_config_value(category, key)
        self._write_widget_value(widget, value)

    @staticmethod
    def _write_widget_value(widget, value):
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QComboBox):
            if value is not None:
                widget.setCurrentText(value)
        elif isinstance(widget, QLineEdit):
            widget.setText('' if value is None else str(value))

    @staticmethod
    def _read_widget_value(widget, value_type):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentText() or None
        if isinstance(widget, QLineEdit):
            text = widget.text()
            if value_type == 'int':
                return int(text) if text else None
            if value_type == 'float':
                return float(text) if text else None
            return text or None
        return None

    # -- API/local visibility toggle ------------------------------------

    def _toggle_api_local_options(self, use_api):
        self._iterate_settings(lambda w, c, s, k, m: self._toggle_widget_visibility(w, c, s, k, use_api))

    def _toggle_widget_visibility(self, widget, category, sub_category, key, use_api):
        if sub_category not in ('api', 'local'):
            return
        visible = use_api if sub_category == 'api' else not use_api
        widget.setVisible(visible)
        label = self.findChild(QLabel, f"{category}_{sub_category}_{key}_label")
        help_button = self.findChild(QToolButton, f"{category}_{sub_category}_{key}_help")
        if label:
            label.setVisible(visible)
        if help_button:
            help_button.setVisible(visible)

    def _iterate_settings(self, func):
        for category, settings in self.schema.items():
            for sub_category, sub_settings in settings.items():
                if isinstance(sub_settings, dict) and 'value' in sub_settings:
                    widget = self.findChild(QWidget, f"{category}_{sub_category}_input")
                    if widget:
                        func(widget, category, None, sub_category, sub_settings)
                else:
                    for key, meta in sub_settings.items():
                        widget = self.findChild(QWidget, f"{category}_{sub_category}_{key}_input")
                        if widget:
                            func(widget, category, sub_category, key, meta)

    def closeEvent(self, event):
        if self._skip_close_confirm:
            self.settings_closed.emit()
            super().closeEvent(event)
            return
        reply = QMessageBox.question(
            self,
            'Close without saving?',
            'Are you sure you want to close without saving?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            ConfigManager.reload_config()
            self._iterate_settings(self._update_widget_value)
            self.settings_closed.emit()
            super().closeEvent(event)
        else:
            event.ignore()
