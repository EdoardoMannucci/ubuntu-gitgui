#!/usr/bin/env bash
# create_deb.sh — package ubuntu-gitgui into a .deb for Ubuntu / Debian
#
# Prerequisites:
#   1. Run ./build.sh first to produce dist/ubuntu-gitgui/
#   2. dpkg-deb must be available (apt install dpkg on Debian/Ubuntu)
#
# Usage:
#   chmod +x create_deb.sh
#   ./create_deb.sh [VERSION]
#
#   VERSION defaults to "0.3.0-alpha" when not supplied.
#
# Output:
#   ubuntu-gitgui_<VERSION>_amd64.deb
#
# The .deb installs files to:
#   /opt/ubuntu-gitgui/          — executable bundle
#   /usr/share/pixmaps/          — application icon (PNG)
#   /usr/share/applications/     — .desktop launcher

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VERSION="${1:-0.3.0-alpha}"
ARCH="amd64"
PACKAGE="ubuntu-gitgui"
DEB_NAME="${PACKAGE}_${VERSION}_${ARCH}"
DEB_DIR="$SCRIPT_DIR/deb_build/${DEB_NAME}"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ ! -d "$SCRIPT_DIR/dist/ubuntu-gitgui" ]; then
    echo "[deb] ERROR: dist/ubuntu-gitgui/ not found."
    echo "[deb]        Run ./build.sh first, then re-run this script."
    exit 1
fi

if ! command -v dpkg-deb &>/dev/null; then
    echo "[deb] ERROR: dpkg-deb not found.  Install with:  sudo apt install dpkg"
    exit 1
fi

echo "[deb] Building .deb package  version=${VERSION}  arch=${ARCH}"

# ── Clean previous deb build directory ───────────────────────────────────────
rm -rf "$SCRIPT_DIR/deb_build"

# ── Create directory structure ────────────────────────────────────────────────
install -d "${DEB_DIR}/DEBIAN"
install -d "${DEB_DIR}/opt/${PACKAGE}"
install -d "${DEB_DIR}/usr/share/pixmaps"
install -d "${DEB_DIR}/usr/share/applications"

# ── Copy the PyInstaller bundle ───────────────────────────────────────────────
cp -r "$SCRIPT_DIR/dist/ubuntu-gitgui/." "${DEB_DIR}/opt/${PACKAGE}/"
chmod +x "${DEB_DIR}/opt/${PACKAGE}/${PACKAGE}"
echo "[deb] Copied dist/ubuntu-gitgui → /opt/${PACKAGE}"

# ── Install the application icon to /usr/share/pixmaps/ ─────────────────────
cp "$SCRIPT_DIR/ubuntu-gitgui.png" "${DEB_DIR}/usr/share/pixmaps/ubuntu-gitgui.png"
echo "[deb] Installed icon → /usr/share/pixmaps/ubuntu-gitgui.png"

# ── Write the .desktop file ───────────────────────────────────────────────────
cat > "${DEB_DIR}/usr/share/applications/ubuntu-gitgui.desktop" <<'DESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=ubuntu-gitgui
GenericName=Git GUI Client
Comment=Open-source Git GUI client for Linux — a community-driven alternative to GitKraken
Exec=/opt/ubuntu-gitgui/ubuntu-gitgui
Icon=ubuntu-gitgui
Terminal=false
StartupNotify=true
StartupWMClass=ubuntu-gitgui
Categories=Development;RevisionControl;
Keywords=git;version control;repository;diff;commit;branch;
MimeType=inode/directory;
DESKTOP
echo "[deb] Wrote /usr/share/applications/ubuntu-gitgui.desktop"

# ── Write DEBIAN/control ──────────────────────────────────────────────────────
cat > "${DEB_DIR}/DEBIAN/control" <<CONTROL
Package: ubuntu-gitgui
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: ubuntu-gitgui contributors <https://github.com/your-org/ubuntu-gitgui>
Installed-Size: $(du -sk "${DEB_DIR}/opt" | cut -f1)
Depends: libgl1, libglib2.0-0, libdbus-1-3
Section: devel
Priority: optional
Homepage: https://github.com/your-org/ubuntu-gitgui
Description: Open-source Git GUI client for Linux
 A community-driven, free alternative to GitKraken.
 Built with Python 3 and PyQt6, it provides an interactive commit
 graph, staging area, diff viewer, and multi-profile SSH/HTTPS
 authentication — entirely self-contained, no Electron overhead.
CONTROL

# ── Write DEBIAN/postinst (update icon cache) ────────────────────────────────
cat > "${DEB_DIR}/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v update-icon-caches >/dev/null 2>&1; then
    update-icon-caches /usr/share/pixmaps || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
POSTINST
chmod 0755 "${DEB_DIR}/DEBIAN/postinst"

# ── Write DEBIAN/prerm (remove pixmaps entry) ────────────────────────────────
cat > "${DEB_DIR}/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if command -v update-icon-caches >/dev/null 2>&1; then
    update-icon-caches /usr/share/pixmaps || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
POSTRM
chmod 0755 "${DEB_DIR}/DEBIAN/postrm"

# ── Build the .deb ────────────────────────────────────────────────────────────
DEB_OUT="$SCRIPT_DIR/${DEB_NAME}.deb"
dpkg-deb --build --root-owner-group "${DEB_DIR}" "${DEB_OUT}"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  .deb package built successfully!"
echo ""
echo "  File    : ${DEB_OUT}"
echo "  Install : sudo dpkg -i ${DEB_NAME}.deb"
echo "  Remove  : sudo dpkg -r ubuntu-gitgui"
echo "══════════════════════════════════════════════════════════════════════"
