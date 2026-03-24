"""
ProfileDialog — QDialog for managing Git identity profiles.

Layout:
    ┌─────────────────────────────────────────────────────────┐
    │  Profiles                                 [+ Add] [Edit] │
    │  ┌───────────────────────────────────────────────────┐  │
    │  │ ● Work     jane@company.com                       │  │
    │  │   Personal john@gmail.com                         │  │
    │  └───────────────────────────────────────────────────┘  │
    │                                    [Delete] [Set Active] │
    │─────────────────────────────────────────────────────────│
    │  Active profile: Work <jane@company.com>                 │
    │                                              [Close]     │
    └─────────────────────────────────────────────────────────┘

A nested _ProfileFormDialog handles the add / edit form.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.controllers.profile_controller import ProfileController
from src.models.profile import Profile


# ── Form dialog (add / edit a single profile) ─────────────────────────────────

class _ProfileFormDialog(QDialog):
    """Modal dialog to create or edit a single profile."""

    def __init__(self, parent: QWidget | None = None, profile: Profile | None = None) -> None:
        super().__init__(parent)
        self._profile = profile  # None → create mode, Profile → edit mode
        self.setWindowTitle("Edit Profile" if profile else "Add Profile")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build_ui()
        if profile:
            self._populate(profile)

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g. Work, Personal, Open-Source")
        form.addRow("Profile name:", self._name_input)

        self._git_name_input = QLineEdit()
        self._git_name_input.setPlaceholderText("Your full name (git user.name)")
        form.addRow("Git name:", self._git_name_input)

        self._git_email_input = QLineEdit()
        self._git_email_input.setPlaceholderText("your@email.com (git user.email)")
        form.addRow("Git email:", self._git_email_input)

        # SSH key row: text field + browse button
        ssh_row = QHBoxLayout()
        self._ssh_input = QLineEdit()
        self._ssh_input.setPlaceholderText("/home/you/.ssh/id_rsa_work  (optional)")
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_ssh_key)
        ssh_row.addWidget(self._ssh_input)
        ssh_row.addWidget(browse_btn)
        form.addRow("SSH key:", ssh_row)

        layout.addLayout(form)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, profile: Profile) -> None:
        """Pre-fill the form with existing profile data (edit mode)."""
        self._name_input.setText(profile.name)
        self._git_name_input.setText(profile.git_name)
        self._git_email_input.setText(profile.git_email)
        self._ssh_input.setText(profile.ssh_key_path)

    # ── Slots ─────────────────────────────────────────────────────────

    def _browse_ssh_key(self) -> None:
        """Open a file picker to select an SSH private key."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH Private Key",
            str(
                # Default to ~/.ssh if it exists
                __import__("pathlib").Path.home() / ".ssh"
            ),
            "All Files (*)",
        )
        if path:
            self._ssh_input.setText(path)

    def _on_accept(self) -> None:
        """Validate inputs before closing."""
        if not self._name_input.text().strip():
            QMessageBox.warning(self, "Validation", "Profile name cannot be empty.")
            return
        if not self._git_name_input.text().strip():
            QMessageBox.warning(self, "Validation", "Git name cannot be empty.")
            return
        if not self._git_email_input.text().strip():
            QMessageBox.warning(self, "Validation", "Git email cannot be empty.")
            return
        self.accept()

    # ── Result accessor ───────────────────────────────────────────────

    def get_profile(self) -> Profile:
        """Return a Profile object built from the form's current values.

        Call this only after the dialog has been accepted.
        """
        profile_id = self._profile.id if self._profile else None
        return Profile(
            id=profile_id or __import__("uuid").uuid4().__str__(),
            name=self._name_input.text().strip(),
            git_name=self._git_name_input.text().strip(),
            git_email=self._git_email_input.text().strip(),
            ssh_key_path=self._ssh_input.text().strip(),
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
        active_marker = "● " if is_active else "  "
        ssh_indicator = "  [SSH]" if profile.ssh_key_path.strip() else ""
        return f"{active_marker}{profile.name}  —  {profile.git_name} <{profile.git_email}>{ssh_indicator}"


# ── Main ProfileDialog ────────────────────────────────────────────────────────

class ProfileDialog(QDialog):
    """Main profile management dialog.

    Displays the full list of profiles with actions to add, edit, delete,
    and set the active profile. Changes are applied immediately via the
    ProfileController passed at construction time.
    """

    def __init__(self, controller: ProfileController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self.setWindowTitle("Manage Profiles — Identity Manager")
        self.setModal(True)
        self.setMinimumSize(560, 380)
        self._build_ui()
        self._refresh_list()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Header label ──────────────────────────────────────────
        header = QLabel("Git identity profiles let you switch between different user names,\n"
                        "email addresses and SSH keys without touching your global git config.")
        header.setWordWrap(True)
        header.setObjectName("section_title")
        root.addWidget(header)

        # ── List + side buttons ───────────────────────────────────
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

        # ── Active profile status bar ─────────────────────────────
        self._active_label = QLabel()
        self._active_label.setObjectName("active_profile_label")
        self._update_active_label()
        root.addWidget(self._active_label)

        # ── Close button ──────────────────────────────────────────
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        root.addWidget(close_box)

    # ── List management ───────────────────────────────────────────────

    def _refresh_list(self) -> None:
        """Rebuild the list widget from the controller's current profile data."""
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

            # Restore selection after refresh
            if profile.id == current_id:
                self._list.setCurrentItem(item)

        self._update_active_label()

    def _update_active_label(self) -> None:
        active = self._ctrl.active_profile
        if active:
            self._active_label.setText(
                f"Active profile:  {active.name}  —  {active.git_name} <{active.git_email}>"
            )
        else:
            self._active_label.setText("Active profile:  (none)")

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_selection_changed(self, current: QListWidgetItem | None, _: QListWidgetItem | None) -> None:
        has_selection = current is not None
        self._edit_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        self._activate_btn.setEnabled(has_selection)

    def _add_profile(self) -> None:
        form = _ProfileFormDialog(parent=self)
        if form.exec() == QDialog.DialogCode.Accepted:
            new_profile = form.get_profile()
            self._ctrl.add_profile(new_profile)
            self._refresh_list()

    def _edit_profile(self) -> None:
        item: _ProfileListItem | None = self._list.currentItem()  # type: ignore[assignment]
        if item is None:
            return
        form = _ProfileFormDialog(parent=self, profile=item.profile)
        if form.exec() == QDialog.DialogCode.Accepted:
            updated = form.get_profile()
            self._ctrl.update_profile(updated)
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
        if answer == QMessageBox.StandardButton.Yes:
            self._ctrl.delete_profile(item.profile.id)
            self._refresh_list()

    def _activate_profile(self) -> None:
        item: _ProfileListItem | None = self._list.currentItem()  # type: ignore[assignment]
        if item is None:
            return
        self._ctrl.activate_profile(item.profile.id)
        self._refresh_list()
        QMessageBox.information(
            self,
            "Profile Activated",
            f"<b>{item.profile.name}</b> is now the active profile.<br><br>"
            + (
                f"GIT_SSH_COMMAND has been set to use:<br><code>{item.profile.ssh_key_path}</code>"
                if item.profile.ssh_key_path.strip()
                else "No SSH key configured — using system defaults."
            ),
        )
