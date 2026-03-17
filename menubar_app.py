"""
Writers Room — Menu Bar App

Entry point. A rumps.App that:
  - Loads the note index in a background thread at startup
  - Presents a floating NSPanel search UI on demand
  - Exposes Preferences and Re-index Notes in the menu
"""

import sys
import subprocess
import threading
from pathlib import Path

import rumps

from searcher import NotesSearcher
from preferences import Preferences, PreferencesWindowController, make_prefs_controller
from search_panel import SearchPanel
from utils import call_on_main


class WRApp(rumps.App):

    def __init__(self) -> None:
        super().__init__(
            name="Writers Room",
            title="✦ WR",       # text shown in menu bar (replace with icon path later)
            quit_button=None,   # we add our own Quit item for control
        )
        self._prefs:       Preferences                        = Preferences()
        self._searcher:    NotesSearcher                      = NotesSearcher()
        self._panel:       SearchPanel | None                 = None
        self._prefs_ctrl:  PreferencesWindowController | None = None

        self.menu = [
            rumps.MenuItem("Search Notes", callback=self._toggle_panel, key="space"),
            None,
            rumps.MenuItem("Preferences…", callback=self._open_prefs, key=","),
            rumps.MenuItem("Re-index Notes", callback=self._reindex),
            None,
            rumps.MenuItem("Quit Writers Room", callback=self._quit),
        ]

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _start_index_load(self) -> None:
        """Kick off background index load. Called just before the run loop."""
        threading.Thread(target=self._load_index_bg, daemon=True).start()

    def _load_index_bg(self) -> None:
        try:
            self._searcher.load_index()
            call_on_main(self._on_index_ready)
        except Exception as e:
            msg = str(e)
            call_on_main(lambda: self._on_index_error(msg))

    def _on_index_ready(self) -> None:
        """Called on main thread once the index is in memory."""
        self._panel = SearchPanel(self._searcher, self._prefs)

    def _on_index_error(self, msg: str) -> None:
        rumps.notification(
            title="Writers Room",
            subtitle="Index error",
            message=msg,
        )

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    @rumps.clicked("Search Notes")
    def _toggle_panel(self, _) -> None:
        if self._panel is None:
            rumps.notification(
                title="Writers Room",
                subtitle="Not ready yet",
                message="Index is still loading — try again in a moment.",
            )
            return
        self._panel.toggle()

    @rumps.clicked("Preferences…")
    def _open_prefs(self, _) -> None:
        if self._prefs_ctrl is None:
            self._prefs_ctrl = make_prefs_controller(
                prefs=self._prefs,
                searcher=self._searcher,
            )
        self._prefs_ctrl.show()

    @rumps.clicked("Re-index Notes")
    def _reindex(self, _) -> None:
        """Run indexer.py in the background. Notifies on completion."""
        def run():
            indexer = str(Path(__file__).parent / "indexer.py")
            result  = subprocess.run(
                [sys.executable, indexer],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                n = self._searcher.reload_index()
                call_on_main(lambda: rumps.notification(
                    "Writers Room", "Re-index complete",
                    f"{n} notes indexed and ready.",
                ))
            else:
                err = (result.stderr or result.stdout or "Unknown error")[:200]
                call_on_main(lambda: rumps.notification(
                    "Writers Room", "Re-index failed", err,
                ))

        threading.Thread(target=run, daemon=True).start()
        rumps.notification(
            title="Writers Room",
            subtitle="Re-indexing…",
            message="This may take a minute. You'll get a notification when done.",
        )

    @rumps.clicked("Quit Writers Room")
    def _quit(self, _) -> None:
        rumps.quit_application()

    # ------------------------------------------------------------------
    # Override run() to load index before entering the run loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        # Start background index load before entering the run loop
        self._start_index_load()
        # rumps handles NSApplicationActivationPolicyAccessory automatically
        super().run()


if __name__ == "__main__":
    WRApp().run()
