# League PhD Desktop App (macOS & Windows)

Desktop app for [League PhD](https://www.leaguephd.com/), updated to support **macOS** (Apple Silicon & Intel) and modern Python / PyQt6.

## Running on macOS

### Option 1: Standalone macOS `.app` Bundle
Double-click `dist/League PhD.app` (or move it to `/Applications`).

### Option 2: Run from Terminal
```bash
./.venv/bin/python leaguephd.py
```

## Rebuilding `League PhD.app`
```bash
./.venv/bin/pyinstaller --noconfirm --windowed --name "League PhD" --icon "assets/icon.icns" --add-data "version.txt:." --add-data "assets:assets" leaguephd.py
```
