#!/usr/bin/env python3
import curses
import sys
from abc import ABC, abstractmethod
from typing import Any


class WinxTuiApp(ABC):
    """
    Abstract Base Class for Terminal User Interfaces using Curses.
    Provides the standard wrapper and exception handling loop.
    """

    def __init__(self) -> None:
        self._running = True

    def run(self) -> None:
        """Entry point for the TUI."""
        try:
            # curses.wrapper handles init/teardown of colors, keypad, echo, etc.
            curses.wrapper(self._main_loop)
        except curses.error as e:
            # Fallback for Windows users missing windows-curses
            if sys.platform == "win32":
                print(f"WinxTui Error: {e}")
                print("On Windows, please run: pip install windows-curses")
            else:
                print(f"Curses Error: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(0)

    def _main_loop(self, stdscr: Any) -> None:
        """The main event loop. Override setup/draw/input methods, not this."""
        # Standard setup
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(False)  # Blocking input by default
        stdscr.keypad(True)
        curses.start_color()
        self.setup_colors()

        while self._running:
            h, w = stdscr.getmaxyx()
            stdscr.erase()

            self.draw(stdscr, h, w)
            stdscr.refresh()

            key = stdscr.getch()
            self.handle_input(stdscr, key)

    def setup_colors(self) -> None:
        """Override to define color pairs."""
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)

    @abstractmethod
    def draw(self, stdscr: Any, h: int, w: int) -> None:
        """Render the UI."""
        pass

    @abstractmethod
    def handle_input(self, stdscr: Any, key: int) -> None:
        """Handle key presses."""
        pass
