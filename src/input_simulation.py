import os
import signal
import subprocess
import sys
import time

from pynput.keyboard import Controller as PynputController, Key

from utils import ConfigManager


def run_command_or_exit_on_failure(command):
    """Run a shell command and exit if it fails."""
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        sys.exit(1)


class InputSimulator:
    """Simulate keyboard input across platforms."""

    def __init__(self):
        self.input_method = ConfigManager.get_config_value('post_processing', 'input_method')
        self.dotool_process = None
        self.keyboard = None

        if self.input_method == 'pynput':
            self.keyboard = PynputController()
        elif self.input_method == 'dotool':
            self._initialize_dotool()

    # -- public ---------------------------------------------------------

    def typewrite(self, text):
        """
        Send `text` to the focused window.

        On Windows the per-character pynput approach was unreliable for
        Unicode (especially Cyrillic / characters with no virtual-key
        code) — text would silently fail to appear in any window. The
        clipboard-paste path used here is robust for any UTF-16 text and
        works in normal *and* elevated windows (provided the running
        process itself has matching or higher integrity level).
        """
        if not text:
            return
        interval = ConfigManager.get_config_value('post_processing', 'writing_key_press_delay') or 0.005
        if self.input_method == 'pynput':
            if sys.platform == 'win32':
                if not self._typewrite_paste_windows(text):
                    self._typewrite_pynput(text, interval)  # fallback
            else:
                self._typewrite_pynput(text, interval)
        elif self.input_method == 'ydotool':
            self._typewrite_ydotool(text, interval)
        elif self.input_method == 'dotool':
            self._typewrite_dotool(text, interval)

    def cleanup(self):
        if self.input_method == 'dotool':
            self._terminate_dotool()

    # -- pynput per-character -------------------------------------------

    def _typewrite_pynput(self, text, interval):
        for char in text:
            try:
                self.keyboard.press(char)
                self.keyboard.release(char)
            except Exception:
                continue
            time.sleep(interval)

    # -- Windows clipboard-paste ----------------------------------------

    def _typewrite_paste_windows(self, text):
        """Copy `text` to the clipboard, send Ctrl+V, restore the previous
        clipboard contents. Returns True on success, False if anything
        went wrong (caller falls back to per-character typing).
        """
        try:
            import pyperclip
        except ImportError:
            return False

        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None

        try:
            pyperclip.copy(text)
        except Exception:
            return False

        # Brief delay so the target app sees the clipboard update before we paste
        time.sleep(0.05)

        try:
            self.keyboard.press(Key.ctrl)
            self.keyboard.press('v')
            time.sleep(0.02)
            self.keyboard.release('v')
            self.keyboard.release(Key.ctrl)
        except Exception:
            return False

        # Restore the previous clipboard contents after the paste settles
        if previous is not None:
            time.sleep(0.15)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
        return True

    # -- Linux backends -------------------------------------------------

    def _initialize_dotool(self):
        self.dotool_process = subprocess.Popen("dotool", stdin=subprocess.PIPE, text=True)
        assert self.dotool_process.stdin is not None

    def _terminate_dotool(self):
        if self.dotool_process:
            os.kill(self.dotool_process.pid, signal.SIGINT)
            self.dotool_process = None

    def _typewrite_ydotool(self, text, interval):
        run_command_or_exit_on_failure([
            "ydotool", "type",
            "--key-delay", str(interval * 1000),
            "--", text,
        ])

    def _typewrite_dotool(self, text, interval):
        assert self.dotool_process and self.dotool_process.stdin
        self.dotool_process.stdin.write(f"typedelay {interval * 1000}\n")
        self.dotool_process.stdin.write(f"type {text}\n")
        self.dotool_process.stdin.flush()
