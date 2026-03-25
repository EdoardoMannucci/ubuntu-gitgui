"""
ProfileDialog — QDialog for managing Git identity profiles.

Layout:
    ┌─────────────────────────────────────────────────────────┐
    │  Profiles                                 [+ Add] [Edit] │
    │  ┌───────────────────────────────────────────────────┐  │
    │  │ ● Work     jane@company.com          [SSH]        │  │
    │  │   GitHub   john@gmail.com            [HTTPS]      │  │
    │  │   Server   admin@server.com          [System]     │  │
    │  └───────────────────────────────────────────────────┘  │
    │                                    [Delete] [Set Active] │
    │─────────────────────────────────────────────────────────│
    │  Active profile: Work <jane@company.com>                 │
    │                                              [Close]     │
    └─────────────────────────────────────────────────────────┘

A nested _ProfileFormDialog handles the add / edit form, which includes
an authentication method selector (SSH Key / HTTPS Token / System Default)
and an "Import from Global Git" button to auto-populate name and email.
"""

import subprocess
import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.controllers.profile_controller import ProfileController
from src.models.profile import Profile
from src.utils.credentials import AuthMethod, delete_token, get_token, store_token


# ── Form dialog (add / edit a single profile) ─────────────────────────────────

class _ProfileFormDialog(QDialog):
    """Modal dialog to create or edit a single profile.

    The dialog lets the user choose between two authentication methods:
      - SSH Key  → shows a file-picker for the private key path
      - HTTPS Token → shows Username + masked Token fields; the token is
                      stored in the OS keyring and NEVER in the JSON file.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        profile: Profile | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile  # None → create mode, Profile → edit mode
        self.setWindowTitle("Edit Profile" if profile else "Add Profile")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build_ui()
        if profile:
            self._populate(profile)
        else:
            self._switch_auth(AuthMethod.SSH)   # default to SSH

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # ── Basic identity ─────────────────────────────────────────
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g. Work, Personal, Open-Source")
        form.addRow("Profile name:", self._name_input)

        self._git_name_input = QLineEdit()
        self._git_name_input.setPlaceholderText("Your full name (git user.name)")
        form.addRow("Git name:", self._git_name_input)

        self._git_email_input = QLineEdit()
        self._git_email_input.setPlaceholderText("your@email.com (git user.email)")
        form.addRow("Git email:", self._git_email_input)

        # Import from global git config button
        import_row = QHBoxLayout()
        import_row.addStretch()
        self._import_git_btn = QPushButton("\u2b07  Import from Global Git")
        self._import_git_btn.setToolTip(
            "Auto-populate Name and Email from your global ~/.gitconfig"
        )
        self._import_git_btn.clicked.connect(self._import_from_global_git)
        import_row.addWidget(self._import_git_btn)
        form.addRow("", import_row)

        layout.addLayout(form)

        # ── Auth method selector ───────────────────────────────────
        auth_label = QLabel("Authentication:")
        auth_label.setObjectName("section_title")
        layout.addWidget(auth_label)

        radio_row = QHBoxLayout()
        self._radio_ssh    = QRadioButton("SSH Key")
        self._radio_https  = QRadioButton("HTTPS  (Token / Password)")
        self._radio_system = QRadioButton("System Default  (SSH Agent / Credential Helper)")
        self._radio_group = QButtonGroup(self)
        self._radio_group.addButton(self._radio_ssh,    0)
        self._radio_group.addButton(self._radio_https,  1)
        self._radio_group.addButton(self._radio_system, 2)
        self._radio_ssh.setChecked(True)
        radio_row.addWidget(self._radio_ssh)
        radio_row.addWidget(self._radio_https)
        radio_row.addWidget(self._radio_system)
        radio_row.addStretch()
        layout.addLayout(radio_row)

        # ── SSH frame ─────────────────────────────────────────────
        self._ssh_frame = QFrame()
        ssh_form = QFormLayout(self._ssh_frame)
        ssh_form.setContentsMargins(0, 4, 0, 0)
        ssh_form.setSpacing(6)
        ssh_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        ssh_row = QHBoxLayout()
        self._ssh_input = QLineEdit()
        self._ssh_input.setPlaceholderText(
            "/home/you/.ssh/id_rsa_work  (leave blank to use system defaults)"
        )
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.setFixedWidth(84)
        browse_btn.clicked.connect(self._browse_ssh_key)
        ssh_row.addWidget(self._ssh_input)
        ssh_row.addWidget(browse_btn)
        ssh_form.addRow("SSH key path:", ssh_row)
        layout.addWidget(self._ssh_frame)

        # ── HTTPS frame ───────────────────────────────────────────
        self._https_frame = QFrame()
        https_form = QFormLayout(self._https_frame)
        https_form.setContentsMargins(0, 4, 0, 0)
        https_form.setSpacing(6)
        https_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._https_user_input = QLineEdit()
        self._https_user_input.setPlaceholderText("GitHub / GitLab username")
        https_form.addRow("Username:", self._https_user_input)

        token_row = QHBoxLayout()
        self._https_token_input = QLineEdit()
        self._https_token_input.setPlaceholderText(
            "Personal Access Token or password"
        )
        self._https_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._show_token_btn = QToolButton()
        self._show_token_btn.setText("\U0001f441")   # 👁 eye icon
        self._show_token_btn.setCheckable(True)
        self._show_token_btn.setFixedWidth(30)
        self._show_token_btn.toggled.connect(self._toggle_token_visibility)
        self._show_token_btn.setToolTip("Show / hide token")
        token_row.addWidget(self._https_token_input)
        token_row.addWidget(self._show_token_btn)
        https_form.addRow("Access token:", token_row)

        note = QLabel(
            "\u26a0  The token is stored in the native OS Secret Service "
            "(GNOME Keyring / KWallet), never in plain text."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #aba9be; font-size: 11px;")
        https_form.addRow("", note)
        layout.addWidget(self._https_frame)

        # Connect radio buttons AFTER frames are created
        self._radio_ssh.toggled.connect(
            lambda checked: self._switch_auth(AuthMethod.SSH) if checked else None
        )
        self._radio_https.toggled.connect(
            lambda checked: self._switch_auth(AuthMethod.HTTPS) if checked else None
        )
        self._radio_system.toggled.connect(
            lambda checked: self._switch_auth(AuthMethod.SYSTEM) if checked else None
        )

        # ── OK / Cancel ───────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Auth method toggle ────────────────────────────────────────────

    def _switch_auth(self, method: AuthMethod) -> None:
        self._ssh_frame.setVisible(method is AuthMethod.SSH)
        self._https_frame.setVisible(method is AuthMethod.HTTPS)
        # SYSTEM: both frames hidden — git uses its own credential helpers

    def _toggle_token_visibility(self, show: bool) -> None:
        self._https_token_input.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )

    # ── Populate (edit mode) ──────────────────────────────────────────

    def _populate(self, profile: Profile) -> None:
        """Pre-fill the form with existing profile data."""
        self._name_input.setText(profile.name)
        self._git_name_input.setText(profile.git_name)
        self._git_email_input.setText(profile.git_email)

        if profile.auth_method == AuthMethod.HTTPS:
            self._radio_https.setChecked(True)
            self._https_user_input.setText(profile.https_username)
            # Load existing token from keyring — show blank if none stored yet
            if profile.https_username:
                token = get_token(profile.https_username)
                self._https_token_input.setText(token)
        elif profile.auth_method == AuthMethod.SYSTEM:
            self._radio_system.setChecked(True)
            self._switch_auth(AuthMethod.SYSTEM)
        else:
            self._radio_ssh.setChecked(True)
            self._ssh_input.setText(profile.ssh_key_path)

    # ── Slots ─────────────────────────────────────────────────────────

    def _import_from_global_git(self) -> None:
        """Read name and email from the global git config and populate the fields."""
        def _git_cfg(key: str) -> str:
            try:
                result = subprocess.run(
                    ["git", "config", "--global", key],
                    capture_output=True, text=True, timeout=5
                )
                return result.stdout.strip()
            except Exception:
                return ""

        name  = _git_cfg("user.name")
        email = _git_cfg("user.email")

        if not name and not email:
            QMessageBox.information(
                self,
                "No Global Config Found",
                "Could not read user.name or user.email from your global git config.\n\n"
                "Run  git config --global user.name \"Your Name\"  to set them.",
            )
            return

        if name:
            self._git_name_input.setText(name)
        if email:
            self._git_email_input.setText(email)

    def _browse_ssh_key(self) -> None:
        from pathlib import Path
        start = str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select SSH Private Key", start, "All Files (*)"
        )
        if path:
            self._ssh_input.setText(path)

    def _on_accept(self) -> None:
        if not self._name_input.text().strip():
            QMessageBox.warning(self, "Validation", "Profile name cannot be empty.")
            return
        if not self._git_name_input.text().strip():
            QMessageBox.warning(self, "Validation", "Git name cannot be empty.")
            return
        if not self._git_email_input.text().strip():
            QMessageBox.warning(self, "Validation", "Git email cannot be empty.")
            return
        if self._radio_https.isChecked():
            if not self._https_user_input.text().strip():
                QMessageBox.warning(self, "Validation", "HTTPS username cannot be empty.")
                return
            if not self._https_token_input.text():
                reply = QMessageBox.question(
                    self, "Empty Token",
                    "No access token entered.\n"
                    "Authentication will likely fail for private repositories.\n\n"
                    "Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        self.accept()  # SSH and SYSTEM need no further validation

    # ── Result accessor ───────────────────────────────────────────────

    def get_profile(self) -> Profile:
        """Build and return a Profile from the form's current values.

        Side effect: if HTTPS auth is selected, the token is persisted to
        the OS keyring HERE (before the caller stores the Profile to JSON).
        Call this only after the dialog has been accepted.
        """
        profile_id = self._profile.id if self._profile else str(uuid.uuid4())

        name      = self._name_input.text().strip()
        git_name  = self._git_name_input.text().strip()
        git_email = self._git_email_input.text().strip()

        if self._radio_https.isChecked():
            username = self._https_user_input.text().strip()
            token    = self._https_token_input.text()
            # Persist token in the OS keyring — not in the JSON profile
            if token:
                store_token(username, token)
            return Profile(
                id=profile_id,
                name=name,
                git_name=git_name,
                git_email=git_email,
                auth_method=AuthMethod.HTTPS.value,
                ssh_key_path="",
                https_username=username,
            )

        if self._radio_system.isChecked():
            return Profile(
                id=profile_id,
                name=name,
                git_name=git_name,
                git_email=git_email,
                auth_method=AuthMethod.SYSTEM.value,
                ssh_key_path="",
                https_username="",
            )

        # SSH (default)
        return Profile(
            id=profile_id,
            name=name,
            git_name=git_name,
            git_email=git_email,
            auth_method=AuthMethod.SSH.value,
            ssh_key_path=self._ssh_input.text().strip(),
            https_username="",
        )


# ── Profile list item helper ──────────────────────────────────────────────────

class _ProfileListItem(QListWidgetItem):
    """QListWidgetItem that carries a reference to its Profile."""

    def __init__(self, profile: Profile, is_active: bool) -> None:
        label = self._build_label(profile, is_active)
        super().__init__(label)
        self.profile = profile

    @staticmethod
    def _build_label(profile: Profile, is_active: bool) -> str:
        active_marker = "\u25cf " if is_active else "  "
        if profile.auth_method == AuthMethod.HTTPS:
            auth_tag = "  [HTTPS]"
        elif profile.auth_method == AuthMethod.SYSTEM:
            auth_tag = "  [System]"
        elif profile.ssh_key_path.strip():
            auth_tag = "  [SSH]"
        else:
            auth_tag = ""
        return (
            f"{active_marker}{profile.name}  \u2014  "
            f"{profile.git_name} <{profile.git_email}>{auth_tag}"
        )


# ── Main ProfileDialog ────────────────────────────────────────────────────────

class ProfileDialog(QDialog):
    """Main profile management dialog.

    Displays the full list of profiles with actions to add, edit, delete,
    and set the active profile.  Changes are applied immediately via the
    ProfileController passed at construction time.
    """

    def __init__(
        self,
        controller: ProfileController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self.setWindowTitle("Manage Profiles \u2014 Identity Manager")
        self.setModal(True)
        self.setMinimumSize(580, 380)
        self._build_ui()
        self._refresh_list()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        header = QLabel(
            "Git identity profiles let you switch between different user names,\n"
            "email addresses, SSH keys, and HTTPS tokens without touching your "
            "global git config."
        )
        header.setWordWrap(True)
        header.setObjectName("section_title")
        root.addWidget(header)

        list_row = QHBoxLayout()

        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(self._edit_profile)
        list_row.addWidget(self._list, stretch=1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self._add_btn = QPushButton("+ Add")
        self._add_btn.clicked.connect(self._add_profile)
        btn_col.addWidget(self._add_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._edit_profile)
        btn_col.addWidget(self._edit_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.setObjectName("danger_btn")
        self._delete_btn.clicked.connect(self._delete_profile)
        btn_col.addWidget(self._delete_btn)

        btn_col.addStretch()

        self._activate_btn = QPushButton("Set Active")
        self._activate_btn.setEnabled(False)
        self._activate_btn.setObjectName("accent_btn")
        self._activate_btn.clicked.connect(self._activate_profile)
        btn_col.addWidget(self._activate_btn)

        list_row.addLayout(btn_col)
        root.addLayout(list_row)

        self._active_label = QLabel()
        self._active_label.setObjectName("active_profile_label")
        self._update_active_label()
        root.addWidget(self._active_label)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        root.addWidget(close_box)

    # ── List management ───────────────────────────────────────────────

    def _refresh_list(self) -> None:
        active = self._ctrl.active_profile
        current_id = (
            self._list.currentItem().profile.id  # type: ignore[attr-defined]
            if self._list.currentItem()
            else None
        )

        self._list.clear()
        for profile in self._ctrl.profiles:
            is_active = (active is not None and active.id == profile.id)
            item = _ProfileListItem(profile, is_active)
            self._list.addItem(item)
            if profile.id == current_id:
                self._list.setCurrentItem(item)

        self._update_active_label()

    def _update_active_label(self) -> None:
        active = self._ctrl.active_profile
        if active:
            if active.auth_method == AuthMethod.HTTPS:
                auth_info = f"HTTPS \u2014 {active.https_username}"
            elif active.auth_method == AuthMethod.SYSTEM:
                auth_info = "System default (SSH agent / credential helper)"
            elif active.ssh_key_path:
                auth_info = "SSH key set"
            else:
                auth_info = "system SSH defaults"
            self._active_label.setText(
                f"Active profile:  {active.name}  \u2014  "
                f"{active.git_name} <{active.git_email}>  ({auth_info})"
            )
        else:
            self._active_label.setText("Active profile:  (none)")

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_selection_changed(
        self,
        current: QListWidgetItem | None,
        _: QListWidgetItem | None,
    ) -> None:
        has = current is not None
        self._edit_btn.setEnabled(has)
        self._delete_btn.setEnabled(has)
        self._activate_btn.setEnabled(has)

    def _add_profile(self) -> None:
        form = _ProfileFormDialog(parent=self)
        if form.exec() == QDialog.DialogCode.Accepted:
            self._ctrl.add_profile(form.get_profile())
            self._refresh_list()

    def _edit_profile(self) -> None:
        item: _ProfileListItem | None = self._list.currentItem()  # type: ignore[assignment]
        if item is None:
            return
        form = _ProfileFormDialog(parent=self, profile=item.profile)
        if form.exec() == QDialog.DialogCode.Accepted:
            self._ctrl.update_profile(form.get_profile())
            self._refresh_list()

    def _delete_profile(self) -> None:
        item: _ProfileListItem | None = self._list.currentItem()  # type: ignore[assignment]
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile <b>{item.profile.name}</b>?<br>This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # Also clean up the stored token from keyring if HTTPS
        if item.profile.auth_method == AuthMethod.HTTPS and item.profile.https_username:
            delete_token(item.profile.https_username)
        self._ctrl.delete_profile(item.profile.id)
        self._refresh_list()

    def _activate_profile(self) -> None:
        item: _ProfileListItem | None = self._list.currentItem()  # type: ignore[assignment]
        if item is None:
            return
        self._ctrl.activate_profile(item.profile.id)
        self._refresh_list()

        p = item.profile
        if p.auth_method == AuthMethod.HTTPS:
            detail = (
                f"HTTPS authentication active.<br>"
                f"Username: <code>{p.https_username}</code><br>"
                "Token retrieved from OS keyring at operation time."
            )
        elif p.auth_method == AuthMethod.SYSTEM:
            detail = (
                "System default authentication active.<br>"
                "Git will use its own credential helper, ssh-agent, or "
                "any other OS-level mechanism already configured."
            )
        elif p.ssh_key_path.strip():
            detail = (
                f"SSH key authentication active.<br>"
                f"Key: <code>{p.ssh_key_path}</code>"
            )
        else:
            detail = "No SSH key configured \u2014 using system SSH defaults."

        QMessageBox.information(
            self,
            "Profile Activated",
            f"<b>{p.name}</b> is now the active profile.<br><br>{detail}",
        )
