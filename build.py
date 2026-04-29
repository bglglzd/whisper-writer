"""
Build a portable Windows release of WhisperWriter.

Two targets:
    build.py            -> CPU-only bundle (~140 MB zipped). Works on any
                           Windows machine, slow transcription.
    build.py --cuda     -> CUDA-enabled bundle (~700 MB zipped, ~1.5 GB
                           unpacked). Bundles cuBLAS + cuDNN. NVIDIA users
                           get GPU acceleration; non-NVIDIA users still
                           work via the runtime CPU fallback in
                           transcription.create_local_model.

Output: dist/WhisperWriter/                        (folder)
        dist/WhisperWriter-Windows-{CPU,CUDA}.zip  (release artifact)

Usage:
    venv/Scripts/python.exe build.py [--cuda]
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / 'dist'
BUILD = ROOT / 'build'
SPEC = ROOT / 'WhisperWriter.spec'

# Modules whose Python imports we don't actually use, but PyInstaller's
# analysis pulls them in transitively. Excluding them shrinks the bundle.
EXCLUDES = [
    'tkinter',
    'matplotlib',
    'IPython',
    'pytest',
    'PIL.ImageQt',
    'webrtcvad',  # PyInstaller hook broken; result_thread falls back to RMS
    'webrtcvad_wheels',
    'PySide6.QtBluetooth',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtNetwork',
    'PySide6.QtNfc',
    'PySide6.QtOpenGL',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtPositioning',
    'PySide6.QtPrintSupport',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuick3D',
    'PySide6.QtQuickWidgets',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSql',
    'PySide6.QtTest',
    'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebSockets',
    'PySide6.QtXml',
]


def clean():
    for p in (DIST, BUILD):
        if p.exists():
            print(f'Cleaning {p} ...')
            shutil.rmtree(p)
    if SPEC.exists():
        SPEC.unlink()


def run_pyinstaller(include_cuda=False):
    sep = ';'  # Windows path-separator for --add-data
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', 'WhisperWriter',
        '--windowed',                 # no console window
        '--noconfirm',
        '--uac-admin',                # request elevation on every launch
        '--icon', str(ROOT / 'assets' / 'ww-logo.ico'),
        '--add-data', f'{ROOT / "assets"}{sep}assets',
        '--add-data', f'{ROOT / "src" / "config_schema.yaml"}{sep}src',
        '--paths', str(ROOT / 'src'),
        '--collect-submodules', 'faster_whisper',
        '--collect-data',       'faster_whisper',
    ]
    for mod in EXCLUDES:
        cmd += ['--exclude-module', mod]
    if include_cuda:
        # Pull in the cuBLAS / cuDNN data files (DLLs) that ctranslate2
        # needs at inference time. PyInstaller's import-following does not
        # discover these because ctranslate2 dlopen()s them at runtime.
        cmd += ['--collect-all', 'nvidia.cublas']
        cmd += ['--collect-all', 'nvidia.cudnn']
    else:
        cmd += ['--exclude-module', 'nvidia']
    cmd.append(str(ROOT / 'src' / 'main.py'))

    print(f'Running PyInstaller (cuda={include_cuda}) ...')
    subprocess.run(cmd, check=True, cwd=ROOT)


def strip_cuda_libs():
    """
    Remove the bulky NVIDIA CUDA DLLs from the bundle (cuBLAS, cuDNN, etc.).
    They get pulled in via ctranslate2's site-packages; we don't need them
    for the CPU-only release.
    """
    target = DIST / 'WhisperWriter' / '_internal'
    if not target.exists():
        return
    removed_bytes = 0
    for sub in ('nvidia',):
        d = target / sub
        if d.exists():
            for f in d.rglob('*'):
                if f.is_file():
                    removed_bytes += f.stat().st_size
            shutil.rmtree(d)
            print(f'Removed {sub}/ ({removed_bytes / 1e6:.1f} MB)')
    # Some NVIDIA DLLs land at the top level too
    for pattern in ('cublas*.dll', 'cudnn*.dll', 'cudart*.dll', 'cufft*.dll'):
        for f in target.glob(pattern):
            print(f'Removing {f.name} ({f.stat().st_size / 1e6:.1f} MB)')
            f.unlink()


def make_zip(target):
    out_dir = DIST / 'WhisperWriter'
    if not out_dir.exists():
        raise RuntimeError(f'{out_dir} not found — PyInstaller failed?')

    suffix = 'CUDA' if target == 'cuda' else 'CPU'
    zip_path = DIST / f'WhisperWriter-Windows-{suffix}.zip'
    if zip_path.exists():
        zip_path.unlink()

    print(f'Zipping {out_dir} -> {zip_path} ...')
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in out_dir.rglob('*'):
            if f.is_file():
                z.write(f, f.relative_to(DIST))
    size_mb = zip_path.stat().st_size / 1e6
    print(f'Done: {zip_path} ({size_mb:.1f} MB)')


def main():
    target = 'cuda' if '--cuda' in sys.argv else 'cpu'
    print(f'=== Build target: {target} ===')
    clean()
    run_pyinstaller(include_cuda=(target == 'cuda'))
    if target == 'cpu':
        strip_cuda_libs()
    make_zip(target)


if __name__ == '__main__':
    main()
