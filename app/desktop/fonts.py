"""Use existing OS fonts also with the offscreen preview font database."""
import os
from pathlib import Path
import sys


def load_system_fonts():
    from PySide6.QtGui import QFontDatabase, QGuiApplication, QFont
    if sys.platform == "win32":
        folder = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "seguisb.ttf", "consola.ttf", "arial.ttf", "tahoma.ttf"):
            path = folder / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.families()
        if QGuiApplication.instance():
            for family in ("Segoe UI", "Arial", "Tahoma"):
                if family in families:
                    QGuiApplication.instance().setFont(QFont(family, 10))
                    break
