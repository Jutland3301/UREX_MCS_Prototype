"""PySide6 GUI for the UREX MCS prototype."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_window import MainWindow

__all__ = ["MainWindow"]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name == "MainWindow":
        from .main_window import MainWindow

        return MainWindow
    raise AttributeError(name)
