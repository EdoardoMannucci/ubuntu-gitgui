"""
ubuntu-gitgui — entry point.

Initialises the QApplication, applies the saved theme stylesheet,
installs a QTranslator for the saved UI language (Phase 13),
creates the MainWindow, and starts the Qt event loop.

Usage:
    python main.py

i18n notes:
    Translations live in src/locales/app_<lang>.qm
    Compile from the .ts source with:
        lrelease src/locales/app_it.ts -qm src/locales/app_it.qm
    If the .qm file is absent the app silently falls back to English.
"""

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QTranslator
from PyQt6.QtWidgets import QApplication

from src.utils.app_settings import load_settings
from src.utils.styles import get_stylesheet
from src.views.main_window import MainWindow


def _install_translator(app: QApplication, language: str) -> None:
    """Load and install a QTranslator for *language* if the .qm file exists.

    The translator is a no-op when the file is absent, so English is used
    as a transparent fallback without any error.
    """
    if language == "en":
        return  # English is the source language — no translation needed

    qm_path = Path(__file__).parent / "src" / "locales" / f"app_{language}.qm"
    translator = QTranslator(app)
    if translator.load(str(qm_path)):
        app.installTranslator(translator)
    else:
        logging.getLogger(__name__).debug(
            "Translation file not found: %s (falling back to English)", qm_path
        )


def main() -> None:
    """Create the application, apply styling, show the window, and run."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    app = QApplication(sys.argv)

    # Load user preferences and install the matching translator
    cfg = load_settings()
    _install_translator(app, str(cfg.get("language", "en")))

    # Apply the selected theme stylesheet before any widget is shown
    app.setStyleSheet(get_stylesheet(str(cfg.get("theme", "dark"))))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
