"""
Input simulation backends for WhisperWriter.

The Windows path uses Win32 SendInput + the clipboard API directly via
ctypes — no pynput, no pyperclip. The previous pynput Controller.press()
based approach silently failed for non-ASCII characters in elevated
processes, and the first pyperclip.copy + pynput Ctrl+V revision never
delivered any actual SendInput events to the foreground window in the
user's environment. This rewrite removes both of those dependencies for
the critical paste path and emits detailed logs so any failure shows up
in `whisper-writer.log`.
"""
import os
import signal
import subprocess
import sys
import time

from pynput.keyboard import Controller as PynputController

from utils import ConfigManager

_IS_WINDOWS = sys.platform == 'win32'

# ---------------------------------------------------------------------------
# Win32 ctypes setup
# ---------------------------------------------------------------------------
if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    VK_CONTROL = 0x11
    VK_V = 0x56

    # On 64-bit Windows, HANDLE / HGLOBAL / pointers are 8 bytes. Without an
    # explicit `restype`, ctypes assumes `int` (4 bytes) and silently
    # truncates the high 32 bits — every subsequent call using that handle
    # fails. We declare argtypes/restype for every function we touch.
    _ULONG_PTR = ctypes.c_size_t  # On Win64, ULONG_PTR is 8 bytes (size_t).

    # ULONG_PTR-sized field used by KEYBDINPUT.dwExtraInfo etc.
    _PVOID = ctypes.c_void_p

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ('wVk', wintypes.WORD),
            ('wScan', wintypes.WORD),
            ('dwFlags', wintypes.DWORD),
            ('time', wintypes.DWORD),
            ('dwExtraInfo', _ULONG_PTR),
        ]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ('dx', wintypes.LONG),
            ('dy', wintypes.LONG),
            ('mouseData', wintypes.DWORD),
            ('dwFlags', wintypes.DWORD),
            ('time', wintypes.DWORD),
            ('dwExtraInfo', _ULONG_PTR),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ('uMsg', wintypes.DWORD),
            ('wParamL', wintypes.WORD),
            ('wParamH', wintypes.WORD),
        ]

    class _INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [
                ('ki', _KEYBDINPUT),
                ('mi', _MOUSEINPUT),
                ('hi', _HARDWAREINPUT),
            ]
        _anonymous_ = ('i',)
        _fields_ = [
            ('type', wintypes.DWORD),
            ('i', _I),
        ]

    # Clipboard
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL

    # Foreground window introspection
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    # Global memory (handles must be 8-byte HANDLEs on x64)
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HANDLE
    _kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalLock.restype = _PVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalFree.restype = wintypes.HANDLE
    _kernel32.GetLastError.argtypes = []
    _kernel32.GetLastError.restype = wintypes.DWORD

    # SendInput — NOTE: do NOT set argtypes/restype here. ctypes caches
    # function signatures on the singleton WinDLL handle, and pynput also
    # calls user32.SendInput with its OWN _INPUT struct. Setting argtypes
    # globally breaks pynput's call ("expected LP__INPUT instance instead
    # of pointer to INPUT"). Our own calls below pass a properly-cast
    # POINTER(_INPUT), so they work without argtypes too.

    # MapVirtualKey for converting VK codes -> scan codes
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT

    # Older keyboard injection API — sometimes bypasses keyboard hooks
    # that block SendInput (some AVs / anti-cheat / RDP clients do this).
    _user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, _ULONG_PTR]
    _user32.keybd_event.restype = None

    MAPVK_VK_TO_VSC = 0
    KEYEVENTF_SCANCODE = 0x0008

    def _foreground_window_info():
        """Return a short string describing the foreground window for logging."""
        try:
            h = _user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(h, buf, 256)
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            return f'hwnd=0x{h & 0xFFFFFFFF:08x} pid={pid.value} title="{buf.value}"'
        except Exception as e:
            return f'<focus query failed: {e}>'

    def _win32_set_clipboard_unicode(text):
        if not _user32.OpenClipboard(None):
            return False, 'OpenClipboard failed'
        try:
            _user32.EmptyClipboard()
            utf16 = text.encode('utf-16-le') + b'\x00\x00'
            h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(utf16))
            if not h_mem:
                return False, 'GlobalAlloc failed'
            ptr = _kernel32.GlobalLock(h_mem)
            if not ptr:
                _kernel32.GlobalFree(h_mem)
                return False, 'GlobalLock failed'
            ctypes.memmove(ptr, utf16, len(utf16))
            _kernel32.GlobalUnlock(h_mem)
            if not _user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                _kernel32.GlobalFree(h_mem)
                return False, f'SetClipboardData failed (GLE={_kernel32.GetLastError()})'
            return True, 'ok'
        finally:
            _user32.CloseClipboard()

    def _win32_send_ctrl_v():
        # Build events with BOTH VK and scan code populated. Hooks that
        # filter by VK see the right keys; hooks that filter by scan code
        # also see the right keys. Highest-compatibility shape.
        sc_ctrl = _user32.MapVirtualKeyW(VK_CONTROL, MAPVK_VK_TO_VSC)
        sc_v = _user32.MapVirtualKeyW(VK_V, MAPVK_VK_TO_VSC)

        inputs = (_INPUT * 4)()
        for i in range(4):
            inputs[i].type = INPUT_KEYBOARD
        inputs[0].ki.wVk, inputs[0].ki.wScan, inputs[0].ki.dwFlags = VK_CONTROL, sc_ctrl, 0
        inputs[1].ki.wVk, inputs[1].ki.wScan, inputs[1].ki.dwFlags = VK_V,       sc_v,    0
        inputs[2].ki.wVk, inputs[2].ki.wScan, inputs[2].ki.dwFlags = VK_V,       sc_v,    KEYEVENTF_KEYUP
        inputs[3].ki.wVk, inputs[3].ki.wScan, inputs[3].ki.dwFlags = VK_CONTROL, sc_ctrl, KEYEVENTF_KEYUP
        n = _user32.SendInput(4, ctypes.cast(inputs, ctypes.POINTER(_INPUT)), ctypes.sizeof(_INPUT))
        if n == 4:
            return True, 'ok'
        return False, f'SendInput sent {n}/4 (GLE={_kernel32.GetLastError()})'

    def _win32_send_ctrl_v_keybd_event():
        # Older API. Some hooks that block WH_KEYBOARD_LL events from
        # SendInput let keybd_event events through (or vice versa) — try
        # both.
        sc_ctrl = _user32.MapVirtualKeyW(VK_CONTROL, MAPVK_VK_TO_VSC)
        sc_v = _user32.MapVirtualKeyW(VK_V, MAPVK_VK_TO_VSC)
        try:
            _user32.keybd_event(VK_CONTROL, sc_ctrl, 0, 0)
            time.sleep(0.01)
            _user32.keybd_event(VK_V,       sc_v,    0, 0)
            time.sleep(0.02)
            _user32.keybd_event(VK_V,       sc_v,    KEYEVENTF_KEYUP, 0)
            _user32.keybd_event(VK_CONTROL, sc_ctrl, KEYEVENTF_KEYUP, 0)
            return True, 'ok'
        except Exception as e:
            return False, f'keybd_event raised {e}'

    def _win32_send_unicode_text(text):
        """Last-resort fallback: send each character as a Unicode VK_PACKET event."""
        events_per_char = 2
        events = (_INPUT * (len(text) * events_per_char))()
        for i, ch in enumerate(text):
            code = ord(ch)
            base = i * events_per_char
            events[base].type = INPUT_KEYBOARD
            events[base].ki.wVk = 0
            events[base].ki.wScan = code
            events[base].ki.dwFlags = KEYEVENTF_UNICODE
            events[base + 1].type = INPUT_KEYBOARD
            events[base + 1].ki.wVk = 0
            events[base + 1].ki.wScan = code
            events[base + 1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        n = _user32.SendInput(len(events), ctypes.cast(events, ctypes.POINTER(_INPUT)), ctypes.sizeof(_INPUT))
        return n == len(events), f'SendInput sent {n}/{len(events)}'


def run_command_or_exit_on_failure(command):
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        sys.exit(1)


class InputSimulator:
    def __init__(self):
        self.input_method = ConfigManager.get_config_value('post_processing', 'input_method')
        self.dotool_process = None
        self.keyboard = None
        if self.input_method == 'pynput':
            self.keyboard = PynputController()
        elif self.input_method == 'dotool':
            self._initialize_dotool()

    # -- public ----------------------------------------------------------

    def typewrite(self, text):
        """Send `text` to the focused window.

        Returns True if a synthetic-input method succeeded, False if every
        method was blocked (in which case the text is still on the
        clipboard for the user to paste manually with Ctrl+V).
        """
        if not text:
            ConfigManager.console_print('typewrite: empty text, nothing to do')
            return True
        ConfigManager.console_print(f'typewrite: {len(text)} chars; method={self.input_method}; platform={sys.platform}')
        if _IS_WINDOWS:
            ConfigManager.console_print(f'typewrite: foreground {_foreground_window_info()}')

        interval = ConfigManager.get_config_value('post_processing', 'writing_key_press_delay') or 0.005

        if self.input_method == 'pynput':
            if _IS_WINDOWS:
                if self._typewrite_win32_paste(text):
                    return True
                ConfigManager.console_print('typewrite: SendInput Ctrl+V blocked, trying keybd_event')
                if self._typewrite_keybd_event_paste():
                    return True
                ConfigManager.console_print('typewrite: keybd_event also blocked, trying Unicode SendInput')
                if self._typewrite_win32_unicode(text):
                    return True
                ConfigManager.console_print('typewrite: all synthetic-input methods blocked')
                ConfigManager.console_print('typewrite: text remains in clipboard — user must Ctrl+V manually')
                return False
            else:
                self._typewrite_pynput(text, interval)
                return True
        elif self.input_method == 'ydotool':
            self._typewrite_ydotool(text, interval)
            return True
        elif self.input_method == 'dotool':
            self._typewrite_dotool(text, interval)
            return True
        return False

    def cleanup(self):
        if self.input_method == 'dotool':
            self._terminate_dotool()

    # -- Windows paste path ---------------------------------------------

    def _typewrite_win32_paste(self, text):
        ok, why = _win32_set_clipboard_unicode(text)
        if not ok:
            ConfigManager.console_print(f'typewrite: clipboard set FAILED ({why})')
            return False
        ConfigManager.console_print('typewrite: clipboard set OK')

        time.sleep(0.04)

        ok, why = _win32_send_ctrl_v()
        if not ok:
            ConfigManager.console_print(f'typewrite: SendInput Ctrl+V FAILED ({why})')
            return False
        ConfigManager.console_print('typewrite: SendInput Ctrl+V OK')
        return True

    def _typewrite_keybd_event_paste(self):
        """Try the older keybd_event API for Ctrl+V. The clipboard is
        already populated by `_typewrite_win32_paste` — we just retry
        sending the keystrokes. Some keyboard hooks block SendInput but
        let keybd_event through (or vice versa)."""
        ok, why = _win32_send_ctrl_v_keybd_event()
        if not ok:
            ConfigManager.console_print(f'typewrite: keybd_event Ctrl+V FAILED ({why})')
            return False
        ConfigManager.console_print('typewrite: keybd_event Ctrl+V OK')
        return True

    def _typewrite_win32_unicode(self, text):
        ok, why = _win32_send_unicode_text(text)
        if not ok:
            ConfigManager.console_print(f'typewrite: SendInput Unicode FAILED ({why})')
            return False
        ConfigManager.console_print(f'typewrite: SendInput Unicode OK ({why})')
        return True

    # -- pynput per-character (cross-platform fallback) -----------------

    def _typewrite_pynput(self, text, interval):
        for char in text:
            try:
                self.keyboard.press(char)
                self.keyboard.release(char)
            except Exception as e:
                ConfigManager.console_print(f'typewrite: pynput press {char!r} failed: {e}')
                continue
            time.sleep(interval)

    # -- Linux backends --------------------------------------------------

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
