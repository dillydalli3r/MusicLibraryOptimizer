"""PySide6 GUI package for the Music Library Optimizer."""
from .theme import THEME, apply_app_theme, set_window_icon, set_appusermodelid

__all__ = ["THEME", "apply_app_theme", "set_window_icon",
           "set_appusermodelid"]


def run():
    """Create the QApplication and run the main window."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont

    from mlo import load_config
    from mlo.deps import HAS_MUTAGEN

    if not HAS_MUTAGEN:
        app = QApplication([])
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None, "Missing dependency",
            "mutagen is required.\n\nInstall it with:\n    pip install "
            "mutagen")
        return 1

    set_appusermodelid()
    app = QApplication([])
    app.setStyle("Fusion")
    app.setApplicationName("Music Library Optimizer")

    # UI font: prefer the Windows 11 variable face.
    from PySide6.QtGui import QFontDatabase
    families = set(QFontDatabase.families())
    for name in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI"):
        if name in families:
            app.setFont(QFont(name, 10))
            break

    config = load_config()
    apply_app_theme(config)

    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()
