# Changelog

All notable changes to ubuntu-gitgui are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

---

## [0.1.0-alpha]

### Added

#### Core UI
- Dark-mode 3-panel layout (sidebar 20 % / commit graph 50 % / staging+diff 30 %)
- "Neon Terminal Editorial" QSS design system with full dark palette
- Light theme ("GitHub Light") as an alternative — switchable live in Settings
- QtAwesome icon set throughout the toolbar and context menus
- About dialog with version and license information

#### Repository management
- **Open** an existing local repository (File → Open Repository)
- **Init** a new empty repository (File → Init Repository)
- **Clone** a remote repository — SSH and HTTPS authenticated (File → Clone Repository)
- Recent-repository combo in the toolbar with persistent history (last 10)
- File → Recent Repositories submenu
- Auto-load the last-used repository on startup

#### Commit graph
- Interactive commit graph rendered as a `QTableView` with a custom delegate
- Colored lane lines for branch topology (topo-order, multi-lane)
- Branch and tag labels on each commit row
- "Load more" pagination (100 commits per page)
- Double-click a row to open the Commit Inspector

#### Commit Inspector
- Full commit metadata (hash, author, date, parent hashes)
- Complete commit message
- Per-file diff viewer with syntax highlighting (Pygments, unified diff)

#### Staging & committing
- Two-panel staging area: **Unstaged files** / **Staged files**
- Stage / unstage individual files or all at once
- **CommitDialog** — spacious modal (900 × 620 min) with:
  - Staging lists + live diff viewer side by side
  - Summary line + body text area
  - Author label pulled from active profile or global git config

#### Diff viewer
- Unified diff with Pygments syntax highlighting
- Addition lines highlighted green, deletion lines red
- Filename header with `a/…` → `b/…` notation

#### Branch & tag management
- Sidebar tree: Local Branches / Remote Branches / Tags
- Single-click checkout of any local branch
- Checkout remote branch (auto-creates local tracking branch)
- Checkout tag (detached HEAD)
- Create new branch from toolbar
- Create annotated or lightweight tag (right-click commit in graph)
- Delete local tag
- Push tag to remote (SSH or HTTPS authenticated)

#### Merge
- Merge any local branch into HEAD via context menu
- Conflict detection: banner shown when merge leaves conflicts
- Abort Merge action clears the conflict state

#### Network operations (async)
- **Fetch** all remotes (prune stale tracking branches)
- **Pull** (fast-forward only)
- **Push** current branch with `--set-upstream`
- All three run in a background QThread — UI stays responsive
- Spinner / status-bar feedback during operations

#### Authentication
- **SSH key** — per-profile private-key path injected via `GIT_SSH_COMMAND`
- **HTTPS Token** — PAT stored in the OS native secret store (GNOME Keyring / KWallet) via `keyring`; injected at call time via a mode-700 `GIT_ASKPASS` temp script — token never written to disk or logged
- **System Default** — no credential injection; git uses its own configured helper or ssh-agent
- Authentication method selector (SSH / HTTPS / System) in profile form

#### Identity profiles
- Unlimited named profiles (name, `git user.name`, `git user.email`, auth method)
- "Import from Global Git" button auto-populates Name and Email from `~/.gitconfig`
- Active profile badge in status bar
- Per-profile SSH key, HTTPS username, and keyring-backed token
- Profile activation instantly updates all network operations

#### Settings
- **Git** tab: read/write global `user.name` and `user.email`
- **General** tab: language selector (EN / IT / FR / ES / DE), theme selector (Dark / Light)
- i18n infrastructure: `QTranslator` + `.ts` / `.qm` workflow (`pylupdate6` / `lrelease`)

#### Packaging
- `build.sh` — one-command PyInstaller `--onedir` bundle
- `ubuntu-gitgui.png` icon bundled inside the binary via `--add-data`
- `create_deb.sh` — produces an installable `.deb` with `/opt`, `/usr/share/pixmaps`, and `/usr/share/applications` entries
- GitHub Actions workflow (`.github/workflows/release.yml`) for automated release on tag push
- `.desktop` launcher file — `Icon=ubuntu-gitgui` resolves via system icon path

### Known issues / limitations (alpha)
- Pull always uses `--ff-only`; no rebase or merge-pull support yet
- No interactive rebase UI
- Conflict resolution is manual (edit files externally, then stage)
- No stash list viewer (stash/pop only)
- Single-repository window (no tabs / multiple repos open at once)
- Translations are stubs only (English is the only complete language)
- Tested on Ubuntu 22.04 x86-64; other distros and Wayland may have rough edges

---

[Unreleased]: https://github.com/EdoardoMannucci/ubuntu-gitgui/compare/v0.1.0-alpha...HEAD
[0.1.0-alpha]: https://github.com/EdoardoMannucci/ubuntu-gitgui/releases/tag/v0.1.0-alpha
