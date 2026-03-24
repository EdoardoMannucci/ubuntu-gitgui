# Contributing to ubuntu-gitgui

Thank you for your interest in contributing! This document explains how to set up the project locally, submit changes, and report bugs.

---

## Local Setup

### Prerequisites
- Python 3.10 or higher
- Git
- A Linux system with a graphical display (X11 or Wayland)

### Steps

```bash
# 1. Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/ubuntu-gitgui.git
cd ubuntu-gitgui

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install all dependencies
pip install -r requirements.txt

# 4. Run the application to verify setup
python main.py
```

You should see the main window open in dark mode. If you encounter any display errors, make sure your `DISPLAY` or `WAYLAND_DISPLAY` environment variable is set correctly.

---

## Project Architecture

The project follows an **MVC (Model-View-Controller)** pattern:

| Directory | Responsibility |
|---|---|
| `src/models/` | Pure data structures — Git state, user profiles, settings |
| `src/views/` | All PyQt6 widgets, dialogs, and layouts |
| `src/controllers/` | Business logic — connects models to views, calls GitPython |
| `src/utils/` | Shared helpers — stylesheets, constants, type definitions |

---

## Code Conventions

- **Language**: Python 3.10+
- **Type hints**: Required on all function signatures
- **Comments**: Write comments in **English**, targeting future contributors
- **Docstrings**: Use Google-style docstrings for all public classes and methods
- **Formatting**: Follow PEP 8. Recommended: use `black` and `isort`
- **Modularity**: Each logical unit lives in its own file. Avoid putting everything in one module

Example:
```python
def get_local_branches(repo: git.Repo) -> list[str]:
    """Return a list of local branch names for the given repository.

    Args:
        repo: An active GitPython Repo instance.

    Returns:
        A list of branch name strings, e.g. ['main', 'feature/my-branch'].
    """
    return [branch.name for branch in repo.branches]
```

---

## Submitting a Pull Request

1. **Create a branch** from `main` with a descriptive name:
   ```bash
   git checkout -b feature/my-new-feature
   # or
   git checkout -b fix/crash-on-empty-repo
   ```

2. **Write your code** following the conventions above.

3. **Test your changes** by running `python main.py` and verifying there are no regressions.

4. **Commit** with a clear message:
   ```bash
   git commit -m "feat: add branch checkout on double-click in sidebar"
   ```

5. **Push** your branch and open a Pull Request on GitHub against the `main` branch.

6. In the PR description, explain:
   - What problem this solves
   - How to test it
   - Any known limitations

---

## Reporting Bugs

Open an issue on GitHub and include:

- **OS and Python version** (`python3 --version`, `uname -a`)
- **Steps to reproduce** the bug
- **Expected behavior** vs **actual behavior**
- **Traceback or error output** (if any)
- **Screenshot** (if it's a visual bug)

---

## Feature Requests

Open an issue with the label `enhancement` and describe:
- The use case / problem you're trying to solve
- Your proposed solution or UI concept
- Any relevant references (e.g., how GitKraken does it)

---

## Code of Conduct

Be respectful and constructive. This is a community project and everyone is welcome, regardless of experience level.
