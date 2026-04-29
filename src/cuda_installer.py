"""
On-demand downloader for the NVIDIA cuBLAS / cuDNN libraries that
ctranslate2 needs for GPU acceleration.

The default release ships *without* these DLLs (~1.3 GB unpacked) so the
download from GitHub stays small (~140 MB). Users who want GPU support
trigger this module from Settings; it pulls the wheels from PyPI and
extracts only the `nvidia/...` subtree into the install directory, where
`_frozen_has_cuda_libs()` (in `transcription.py`) and the DLL search
code (in `main.py`) will pick them up on next launch.
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile


NVIDIA_PACKAGES = ['nvidia-cublas-cu12', 'nvidia-cudnn-cu12']
_USER_AGENT = 'WhisperWriter/1.1 (+https://github.com/bglglzd/whisper-writer)'


def install_dir():
    """Where the bundled `nvidia/...` tree lives at runtime."""
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_relevant():
    """The on-demand installer is only meaningful in a frozen bundle.
    Source-mode users get CUDA libs via their venv's `pip install` flow."""
    return hasattr(sys, '_MEIPASS')


def is_installed():
    """Probe for cublas64_12.dll under the bundle's `nvidia/cublas/bin`."""
    return os.path.isfile(os.path.join(install_dir(), 'nvidia', 'cublas', 'bin', 'cublas64_12.dll'))


def find_wheel_info(package_name):
    """Look up the latest `win_amd64` wheel URL for a PyPI package.

    Returns (url, size_bytes).
    """
    info_url = f'https://pypi.org/pypi/{package_name}/json'
    req = urllib.request.Request(info_url, headers={'User-Agent': _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    version = data['info']['version']
    for entry in data['releases'][version]:
        fn = entry['filename']
        if fn.endswith('.whl') and 'win_amd64' in fn:
            return entry['url'], int(entry.get('size') or 0)
    raise RuntimeError(f'No Windows wheel found for {package_name}@{version}')


def download_with_progress(url, dest_path, progress_cb=None):
    """Stream `url` into `dest_path`, calling `progress_cb(done, total)`."""
    req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get('Content-Length', 0))
        downloaded = 0
        with open(dest_path, 'wb') as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)
    return downloaded


def extract_nvidia_subtree(wheel_path, target_dir):
    """Extract only entries under `nvidia/` from a wheel into `target_dir`.

    Wheels also contain a `*.dist-info/` directory we don't need at
    runtime — skipping it keeps the install slimmer.
    """
    with zipfile.ZipFile(wheel_path) as zf:
        for name in zf.namelist():
            if name.startswith('nvidia/'):
                zf.extract(name, target_dir)


def install(stage_cb=None, progress_cb=None):
    """Download + extract every package in `NVIDIA_PACKAGES`.

    `stage_cb(str)` receives high-level status strings.
    `progress_cb(done_bytes, total_bytes)` receives per-chunk download progress.
    """
    target = install_dir()
    os.makedirs(target, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix='ww_cuda_')
    try:
        for pkg in NVIDIA_PACKAGES:
            if stage_cb:
                stage_cb(f'Looking up {pkg}…')
            url, size = find_wheel_info(pkg)

            if stage_cb:
                size_mb = (size / 1024 / 1024) if size else None
                size_str = f' ({size_mb:.0f} MB)' if size_mb else ''
                stage_cb(f'Downloading {pkg}{size_str}…')

            wheel_path = os.path.join(tmp, os.path.basename(url))
            download_with_progress(url, wheel_path, progress_cb=progress_cb)

            if stage_cb:
                stage_cb(f'Extracting {pkg}…')
            extract_nvidia_subtree(wheel_path, target)
            os.remove(wheel_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
