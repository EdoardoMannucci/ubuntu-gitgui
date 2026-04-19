# ubuntu-gitgui

**A fully open-source, native Git GUI client for Linux — built as a community-driven alternative to GitKraken.**

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)
![Platform: Linux](https://img.shields.io/badge/Platform-Linux-orange.svg)
![Status: Alpha](https://img.shields.io/badge/Status-Alpha-yellow.svg)

---

## Why ubuntu-gitgui?

GitKraken is a great tool, but it is proprietary and requires a paid plan for private repositories. The Linux community deserves a **free, open-source alternative** that is:

- **Native on Linux** — built with Python and PyQt6, no Electron overhead
- **Free forever** — MIT licensed, no paid tiers, no telemetry
- **Multi-user ready** — first-class support for switching Git identities and SSH keys
- **Community-driven** — contributions welcome from day one

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| GUI Framework | PyQt6 |
| Git Backend | GitPython |
| Syntax Highlighting | Pygments |
| Architecture | MVC (Model-View-Controller) |

---

## Features

- [x] **Phase 1** — Dark mode GUI skeleton (3-panel layout, Catppuccin Mocha theme)
- [x] **Phase 2** — Multi-user identity manager (profiles with SSH keys)
- [x] **Phase 3** — Repository open / init / clone + branch sidebar with checkout
- [x] **Phase 4** — Interactive commit graph with colored branch lanes
- [x] **Phase 5** — Staging area: stage / unstage / commit with author identity
- [x] **Phase 6** — Diff viewer with full syntax highlighting (unified diff)
- [x] **Phase 7** — Fetch / Pull / Push toolbar actions (async, SSH-key aware)
- [x] **Phase 8** — Merge via drag & drop, conflict detection, Abort Merge
- [x] **Phase 9** — UI revamp: QtAwesome icons, context menus, About dialog
- [x] **Phase 10** — Recent repository manager + Settings dialog (Git config, i18n)
- [x] **Phase 11** — Commit Inspector: metadata, full message, per-file diff
- [x] **Phase 12** — Recent-repos combo in toolbar, File → Recent Repositories menu
- [x] **Phase 13** — Settings dialog (global Git config, language selection), i18n infrastructure
- [x] **Phase 14** — PyInstaller packaging: `build.sh` + `.desktop` launcher file
- [x] **Phase 15** — Custom native app icon (`ubuntu-gitgui.png`) bundled in binary and `.deb` package; `create_deb.sh` for one-command Debian/Ubuntu packaging

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/your-org/ubuntu-gitgui.git
cd ubuntu-gitgui

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python main.py
```

Requirements: Python 3.10+, a working display (X11 or Wayland).

---

---

## How to Build

Compile the app into a self-contained Linux bundle using [PyInstaller](https://pyinstaller.org):

```bash
# 1. Create and activate the virtual environment (first time only)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # installs PyInstaller too

# 2. Make the build script executable and run it
chmod +x build.sh
./build.sh
```

The script produces a `dist/ubuntu-gitgui/` directory containing the executable and all its dependencies.
The `ubuntu-gitgui.png` icon is automatically bundled inside the directory and embedded in the binary via `--add-data`.

```
dist/ubuntu-gitgui/
├── ubuntu-gitgui          ← the standalone executable
├── ubuntu-gitgui.desktop  ← desktop launcher (Exec= pre-set; Icon= uses bare name)
├── ubuntu-gitgui.png      ← application icon (128×128 PNG, bundled automatically)
├── _internal/             ← bundled libraries and Qt plugins
└── ...
```

### Building a .deb package (Ubuntu / Debian)

After running `./build.sh`, package the app into a `.deb` with a single command:

```bash
chmod +x create_deb.sh
./create_deb.sh 0.3.0-alpha    # pass the version number as an argument

# Install the generated package
sudo dpkg -i ubuntu-gitgui_0.3.0-alpha_amd64.deb
```

The `.deb` installer places the bundle at `/opt/ubuntu-gitgui/`, registers the icon in
`/usr/share/pixmaps/ubuntu-gitgui.png`, and creates a `.desktop` entry in
`/usr/share/applications/` so the app appears in your application launcher automatically.

### Installing to your system launcher (GNOME / KDE) — manual method

```bash
# Copy the bundle to a permanent location
sudo cp -r dist/ubuntu-gitgui /opt/ubuntu-gitgui

# Install the icon so the desktop environment can find it by name
sudo cp dist/ubuntu-gitgui/ubuntu-gitgui.png /usr/share/pixmaps/

# Install the launcher (Icon= is already set to the bare name "ubuntu-gitgui")
cp /opt/ubuntu-gitgui/ubuntu-gitgui.desktop ~/.local/share/applications/

# Update the desktop database
update-desktop-database ~/.local/share/applications/
```

### Translations (i18n)

Translation source files live in `src/locales/`.
To compile an Italian translation:

```bash
# Install Qt tools (one-time)
pip install pyqt6-tools   # provides lrelease / pylupdate6

# Compile the .ts → .qm binary
lrelease src/locales/app_it.ts -qm src/locales/app_it.qm

# To extract new strings from source into the .ts:
pylupdate6 main.py src/views/main_window.py src/views/settings_dialog.py \
    -ts src/locales/app_it.ts
```

Then select **Italiano** in **Settings → Preferences → General** and restart.

---

## Project Structure

```
ubuntu-gitgui/
├── main.py               # Entry point
├── requirements.txt      # Python dependencies
├── src/
│   ├── models/           # Data models (Git state, profiles)
│   ├── views/            # PyQt6 widgets and windows
│   ├── controllers/      # Business logic, connects models and views
│   └── utils/            # Helpers, stylesheets, constants
├── LICENSE
├── README.md
└── CONTRIBUTING.md
```

---

## Contributing

We welcome contributions of all kinds — code, documentation, bug reports, and feature ideas.

See [CONTRIBUTING.md](CONTRIBUTING.md) for full details on how to get started.

---

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I61WKPWM)

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.
