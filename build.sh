#!/usr/bin/env bash
# build.sh — compile ubuntu-gitgui into a standalone Linux bundle
#
# Usage:
#   chmod +x build.sh
#   ./build.sh
#
# Output:  dist/ubuntu-gitgui/ubuntu-gitgui   (executable)
#
# Requirements:
#   pip install pyinstaller          (one-time, inside the venv)
#
# Notes on --onedir vs --onefile:
#   PyQt6 bundles dozens of shared libraries.  --onefile would extract
#   them all to /tmp on every launch, making startup slow.  --onedir
#   keeps everything in dist/ubuntu-gitgui/ and starts instantly.
#
# Distributing:
#   Tar the whole dist/ubuntu-gitgui/ folder.  Users can also install the
#   ubuntu-gitgui.desktop file to add the app to their system launcher.

set -euo pipefail

# ── Resolve project root ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Resolve Python interpreter ───────────────────────────────────────────────
# Priority: explicit $PYTHON env var  →  venv/bin/python  →  system python3
if [ -n "${PYTHON:-}" ]; then
    : # already set by caller
elif [ -d "$SCRIPT_DIR/venv" ] && [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python"
    # Also make the venv's pip/pyinstaller available on PATH
    export PATH="$SCRIPT_DIR/venv/bin:$PATH"
    echo "[build] Using venv Python: $PYTHON"
else
    PYTHON="python3"
    echo "[build] WARNING: No venv/ found. Using system python3 ($(which python3 2>/dev/null || echo 'not found'))."
    echo "[build]          Consider:  python3 -m venv venv && source venv/bin/activate"
fi

echo "[build] Python  : $($PYTHON --version)"
echo "[build] Platform: $(uname -srm)"

# ── Ensure PyInstaller is available ─────────────────────────────────────────
if ! $PYTHON -m PyInstaller --version &>/dev/null; then
    echo "[build] PyInstaller not found — installing..."
    pip install "pyinstaller>=6.0"
fi
echo "[build] PyInstaller: $($PYTHON -m PyInstaller --version)"

# ── Clean previous artifacts ─────────────────────────────────────────────────
echo "[build] Cleaning dist/ and build/ ..."
rm -rf "$SCRIPT_DIR/dist" "$SCRIPT_DIR/build" "$SCRIPT_DIR/ubuntu-gitgui.spec"

# ── Detect the qtawesome data path (fonts, icon metadata) ───────────────────
QTAWESOME_PATH="$($PYTHON -c "import qtawesome, os; print(os.path.dirname(qtawesome.__file__))")"
echo "[build] qtawesome path: $QTAWESOME_PATH"

# ── Run PyInstaller ──────────────────────────────────────────────────────────
echo "[build] Running PyInstaller (--onedir)..."

$PYTHON -m PyInstaller \
    --name "ubuntu-gitgui" \
    --onedir \
    --windowed \
    \
    `# ── Data files ──────────────────────────────────────────────────` \
    --add-data "src/locales:src/locales" \
    --add-data "src/styles:src/styles" \
    --add-data "$QTAWESOME_PATH:qtawesome" \
    \
    `# ── Collect entire packages that use dynamic resource loading ────` \
    --collect-all "qtawesome" \
    --collect-all "PyQt6" \
    \
    `# ── Hidden imports not detected by static analysis ───────────────` \
    --hidden-import "PyQt6.sip" \
    --hidden-import "PyQt6.QtSvg" \
    --hidden-import "PyQt6.QtXml" \
    --hidden-import "git.repo.fun" \
    --hidden-import "gitdb" \
    --hidden-import "gitdb.db" \
    --hidden-import "gitdb.db.loose" \
    --hidden-import "gitdb.db.pack" \
    --hidden-import "gitdb.db.ref" \
    --hidden-import "smmap" \
    --hidden-import "smmap.mman" \
    \
    main.py

# ── Copy the .desktop file into the bundle for convenience ──────────────────
if [ -f "$SCRIPT_DIR/ubuntu-gitgui.desktop" ]; then
    cp "$SCRIPT_DIR/ubuntu-gitgui.desktop" "$SCRIPT_DIR/dist/ubuntu-gitgui/"
    echo "[build] Copied ubuntu-gitgui.desktop into dist/"
fi

# ── Report ───────────────────────────────────────────────────────────────────
DIST_EXE="$SCRIPT_DIR/dist/ubuntu-gitgui/ubuntu-gitgui"
echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  Build complete!"
echo ""
echo "  Bundle : $SCRIPT_DIR/dist/ubuntu-gitgui/"
echo "  Run    : $DIST_EXE"
echo ""
echo "  To add to your system launcher:"
echo "    1. Copy dist/ubuntu-gitgui/ to a permanent location, e.g. /opt/"
echo "    2. Edit ubuntu-gitgui.desktop  →  set Exec= and Icon= to the"
echo "       absolute paths inside that folder."
echo "    3. cp ubuntu-gitgui.desktop ~/.local/share/applications/"
echo "    4. update-desktop-database ~/.local/share/applications/"
echo "══════════════════════════════════════════════════════════════════════"
