"""
Writers Room — Preferences

Persistent settings stored in ~/.config/writers-room/prefs.json.
Also provides the Preferences NSWindow (built programmatically).
"""

import json
import subprocess
import sys
import threading
from pathlib import Path

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSClosableWindowMask,
    NSColor,
    NSFont,
    NSMakeRect,
    NSMiniaturizableWindowMask,
    NSObject,
    NSSegmentedControl,
    NSSegmentStyleRounded,
    NSStepper,
    NSTitledWindowMask,
    NSTextField,
    NSTextFieldCell,
    NSWindow,
    NSWindowController,
)
from utils import call_on_main

PREFS_PATH = Path.home() / ".config" / "writers-room" / "prefs.json"

DEFAULTS: dict = {
    "n_results":      5,
    "default_mode":   "semantic",   # "semantic" | "hybrid" | "keyword"
    "launch_at_login": False,
    "persist_window":  True,        # keep panel open when focus moves elsewhere
    "use_hyde":        False,       # HyDE: embed a hypothetical note instead of raw query
}

LAUNCH_AGENT_PLIST_PATH = (
    Path.home() / "Library" / "LaunchAgents" / "com.writersroom.menubar.plist"
)

_MODE_LABELS = ["Semantic", "Hybrid", "Keyword"]
_MODE_KEYS   = ["semantic", "hybrid", "keyword"]


# ---------------------------------------------------------------------------
# Settings storage
# ---------------------------------------------------------------------------

class Preferences:
    def __init__(self) -> None:
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        if PREFS_PATH.exists():
            try:
                with open(PREFS_PATH) as f:
                    self._data = {**DEFAULTS, **json.load(f)}
            except Exception:
                self._data = dict(DEFAULTS)
        else:
            self._data = dict(DEFAULTS)

    def save(self) -> None:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFS_PATH, "w") as f:
            json.dump(self._data, f, indent=2)

    # ---- n_results ----

    @property
    def n_results(self) -> int:
        return int(self._data.get("n_results", DEFAULTS["n_results"]))

    @n_results.setter
    def n_results(self, v: int) -> None:
        self._data["n_results"] = max(3, min(10, int(v)))
        self.save()

    # ---- default_mode ----

    @property
    def default_mode(self) -> str:
        mode = self._data.get("default_mode", DEFAULTS["default_mode"])
        return mode if mode in _MODE_KEYS else "semantic"

    @default_mode.setter
    def default_mode(self, v: str) -> None:
        if v in _MODE_KEYS:
            self._data["default_mode"] = v
            self.save()

    # ---- launch_at_login ----

    @property
    def launch_at_login(self) -> bool:
        return bool(self._data.get("launch_at_login", DEFAULTS["launch_at_login"]))

    @launch_at_login.setter
    def launch_at_login(self, v: bool) -> None:
        self._data["launch_at_login"] = bool(v)
        self.save()
        _set_launch_at_login(bool(v))

    # ---- persist_window ----

    @property
    def persist_window(self) -> bool:
        return bool(self._data.get("persist_window", DEFAULTS["persist_window"]))

    @persist_window.setter
    def persist_window(self, v: bool) -> None:
        self._data["persist_window"] = bool(v)
        self.save()

    # ---- use_hyde ----

    @property
    def use_hyde(self) -> bool:
        return bool(self._data.get("use_hyde", DEFAULTS["use_hyde"]))

    @use_hyde.setter
    def use_hyde(self, v: bool) -> None:
        self._data["use_hyde"] = bool(v)
        self.save()


# ---------------------------------------------------------------------------
# Launch-at-login helpers (LaunchAgent plist)
# ---------------------------------------------------------------------------

def _set_launch_at_login(enabled: bool) -> None:
    """Write or remove a LaunchAgent plist for this app."""
    app_path = Path(sys.executable)
    script_path = Path(__file__).parent / "menubar_app.py"

    if enabled:
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.writersroom.menubar</string>
    <key>ProgramArguments</key>
    <array>
        <string>{app_path}</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
        LAUNCH_AGENT_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT_PLIST_PATH.write_text(plist_content)
        subprocess.run(
            ["launchctl", "load", str(LAUNCH_AGENT_PLIST_PATH)],
            capture_output=True,
        )
    else:
        if LAUNCH_AGENT_PLIST_PATH.exists():
            subprocess.run(
                ["launchctl", "unload", str(LAUNCH_AGENT_PLIST_PATH)],
                capture_output=True,
            )
            LAUNCH_AGENT_PLIST_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Preferences window
# ---------------------------------------------------------------------------

def _make_label(text: str, x: float, y: float, w: float = 160, h: float = 20) -> NSTextField:
    """Create a non-editable, non-bordered label."""
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    field.setStringValue_(text)
    field.setEditable_(False)
    field.setBordered_(False)
    field.setDrawsBackground_(False)
    field.setFont_(NSFont.systemFontOfSize_(13))
    return field


class PreferencesWindowController(NSWindowController):

    def _build_window(self) -> None:
        W, H = 380, 380
        style = (
            NSTitledWindowMask
            | NSClosableWindowMask
            | NSMiniaturizableWindowMask
        )
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            style,
            NSBackingStoreBuffered,
            False,
        )
        win.setTitle_("Writers Room — Preferences")
        win.center()
        self.setWindow_(win)
        content = win.contentView()

        y = H - 50

        # ---- Number of results ----
        content.addSubview_(_make_label("Results to show:", 20, y))
        self._stepper = NSStepper.alloc().initWithFrame_(NSMakeRect(170, y - 2, 19, 24))
        self._stepper.setMinValue_(3)
        self._stepper.setMaxValue_(10)
        self._stepper.setIntValue_(self._prefs.n_results)
        self._stepper.setIncrement_(1)
        self._stepper.setTarget_(self)
        self._stepper.setAction_("stepperChanged:")
        content.addSubview_(self._stepper)

        self._count_label = NSTextField.alloc().initWithFrame_(NSMakeRect(196, y, 40, 20))
        self._count_label.setStringValue_(str(self._prefs.n_results))
        self._count_label.setEditable_(False)
        self._count_label.setBordered_(False)
        self._count_label.setDrawsBackground_(False)
        self._count_label.setFont_(NSFont.systemFontOfSize_(13))
        content.addSubview_(self._count_label)

        y -= 50

        # ---- Default mode ----
        content.addSubview_(_make_label("Default mode:", 20, y))
        self._mode_control = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(170, y - 2, 190, 26)
        )
        self._mode_control.setSegmentCount_(3)
        for i, label in enumerate(_MODE_LABELS):
            self._mode_control.setLabel_forSegment_(label, i)
        self._mode_control.setSegmentStyle_(NSSegmentStyleRounded)
        self._mode_control.setSelectedSegment_(_MODE_KEYS.index(self._prefs.default_mode))
        content.addSubview_(self._mode_control)

        y -= 50

        # ---- Persist window ----
        self._persist_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 340, 22))
        self._persist_checkbox.setButtonType_(3)   # NSSwitchButton
        self._persist_checkbox.setTitle_("Keep panel open when focus moves away")
        self._persist_checkbox.setFont_(NSFont.systemFontOfSize_(13))
        self._persist_checkbox.setState_(1 if self._prefs.persist_window else 0)
        content.addSubview_(self._persist_checkbox)

        y -= 50

        # ---- HyDE deep semantic search ----
        self._hyde_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 340, 22))
        self._hyde_checkbox.setButtonType_(3)
        self._hyde_checkbox.setTitle_("Deep semantic search (HyDE — better for reflective queries)")
        self._hyde_checkbox.setFont_(NSFont.systemFontOfSize_(13))
        self._hyde_checkbox.setState_(1 if self._prefs.use_hyde else 0)
        content.addSubview_(self._hyde_checkbox)

        y -= 50

        # ---- Launch at login ----
        self._login_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 260, 22))
        self._login_checkbox.setButtonType_(3)
        self._login_checkbox.setTitle_("Launch Writers Room at login")
        self._login_checkbox.setFont_(NSFont.systemFontOfSize_(13))
        self._login_checkbox.setState_(1 if self._prefs.launch_at_login else 0)
        content.addSubview_(self._login_checkbox)

        y -= 50

        # ---- Re-index button ----
        reindex_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 160, 28))
        reindex_btn.setTitle_("Re-index Notes")
        reindex_btn.setTarget_(self)
        reindex_btn.setAction_("reindexClicked:")
        content.addSubview_(reindex_btn)

        self._status_label = NSTextField.alloc().initWithFrame_(NSMakeRect(190, y + 4, 170, 20))
        self._status_label.setStringValue_("")
        self._status_label.setEditable_(False)
        self._status_label.setBordered_(False)
        self._status_label.setDrawsBackground_(False)
        self._status_label.setFont_(NSFont.systemFontOfSize_(11))
        self._status_label.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(self._status_label)

        # ---- Save button ----
        save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 100, 16, 80, 28))
        save_btn.setTitle_("Save")
        save_btn.setTarget_(self)
        save_btn.setAction_("saveClicked:")
        content.addSubview_(save_btn)

    # ---- Actions ----

    @objc.IBAction
    def stepperChanged_(self, sender) -> None:
        val = int(sender.intValue())
        self._count_label.setStringValue_(str(val))

    @objc.IBAction
    def reindexClicked_(self, sender) -> None:
        self._status_label.setStringValue_("Indexing…")
        indexer_path = str(Path(__file__).parent / "indexer.py")

        def run():
            result = subprocess.run(
                [sys.executable, indexer_path],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                n = self._searcher.reload_index()
                call_on_main(lambda: self._status_label.setStringValue_(f"Done — {n} notes"))
            else:
                call_on_main(lambda: self._status_label.setStringValue_("Error — check terminal"))

        threading.Thread(target=run, daemon=True).start()

    @objc.IBAction
    def saveClicked_(self, sender) -> None:
        self._prefs.n_results       = int(self._stepper.intValue())
        self._prefs.default_mode    = _MODE_KEYS[self._mode_control.selectedSegment()]
        self._prefs.persist_window  = bool(self._persist_checkbox.state())
        self._prefs.use_hyde        = bool(self._hyde_checkbox.state())
        self._prefs.launch_at_login = bool(self._login_checkbox.state())
        self.window().orderOut_(None)

    def show(self) -> None:
        self.showWindow_(None)
        self.window().makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)


# Module-level factory — avoids PyObjC intercepting classmethods on NSObject subclasses
def make_prefs_controller(prefs: Preferences, searcher) -> PreferencesWindowController:
    controller = PreferencesWindowController.alloc().init()
    controller._prefs            = prefs
    controller._searcher         = searcher
    controller._status_label     = None
    controller._stepper          = None
    controller._count_label      = None
    controller._mode_control     = None
    controller._login_checkbox   = None
    controller._persist_checkbox = None
    controller._hyde_checkbox    = None
    controller._build_window()
    return controller
