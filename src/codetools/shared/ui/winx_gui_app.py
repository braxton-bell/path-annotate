#!/usr/bin/env python3

import tkinter as tk
from abc import ABC, abstractmethod


class WinxGuiApp(ABC):
    """
    Abstract Base Class for Graphical User Interfaces using Tkinter.
    """

    def __init__(self, title: str = "Winx App", size: str = "600x600") -> None:
        self._root = tk.Tk()
        self._root.title(title)
        self._root.geometry(size)
        self._setup_core_widgets()

    def _setup_core_widgets(self) -> None:
        """Initial widget setup."""
        self.setup_ui(self._root)

    @abstractmethod
    def setup_ui(self, root: tk.Tk) -> None:
        """Build your widgets here."""
        pass

    def run(self) -> None:
        """Start the Tkinter main loop."""
        try:
            self._root.mainloop()
        except Exception as e:
            print(f"WinxGui Error: {e}")
