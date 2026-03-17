"""
Writers Room — Preferences

Persistent settings stored in ~/.config/writers-room/prefs.json.
Provides a tabbed Preferences window (Search · Indexing · General).
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
    NSBezelStyleRounded,
    NSButton,
    NSClosableWindowMask,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSMiniaturizableWindowMask,
    NSObject,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentStyleRounded,
    NSSlider,
    NSStepper,
    NSTabView,
    NSTabViewItem,
    NSTextView,
    NSTitledWindowMask,
    NSTextField,
    NSTextFieldCell,
    NSView,
    NSWindow,
    NSWindowController,
)
from utils import call_on_main

PREFS_PATH = Path.home() / ".config" / "writers-room" / "prefs.json"

DEFAULTS: dict = {
    "n_results":        5,
    "default_mode":     "semantic",   # "semantic" | "hybrid" | "keyword"
    "launch_at_login":  False,
    "persist_window":   True,         # keep panel open when focus moves elsewhere
    "use_hyde":         False,        # HyDE: embed a hypothetical note instead of raw query
    "search_depth":     50,           # 0 = literal/keyword-heavy, 100 = deep semantic
    "skip_short_notes": True,         # filter out trivially short notes from results
    "excluded_folders": [],           # folder names to exclude from search results
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

    # ---- search_depth ----

    @property
    def search_depth(self) -> int:
        return int(self._data.get("search_depth", DEFAULTS["search_depth"]))

    @search_depth.setter
    def search_depth(self, v: int) -> None:
        self._data["search_depth"] = max(0, min(100, int(v)))
        self.save()

    # ---- skip_short_notes ----

    @property
    def skip_short_notes(self) -> bool:
        return bool(self._data.get("skip_short_notes", DEFAULTS["skip_short_notes"]))

    @skip_short_notes.setter
    def skip_short_notes(self, v: bool) -> None:
        self._data["skip_short_notes"] = bool(v)
        self.save()

    # ---- excluded_folders ----

    @property
    def excluded_folders(self) -> list[str]:
        return list(self._data.get("excluded_folders", DEFAULTS["excluded_folders"]))

    @excluded_folders.setter
    def excluded_folders(self, v: list[str]) -> None:
        self._data["excluded_folders"] = [s.strip() for s in v if s.strip()]
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
# UI helpers
# ---------------------------------------------------------------------------

def _make_label(text: str, x: float, y: float, w: float = 200, h: float = 20,
                size: float = 13, color=None, bold: bool = False) -> NSTextField:
    """Create a non-editable, non-bordered label."""
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    field.setStringValue_(text)
    field.setEditable_(False)
    field.setBordered_(False)
    field.setDrawsBackground_(False)
    if bold:
        field.setFont_(NSFont.boldSystemFontOfSize_(size))
    else:
        field.setFont_(NSFont.systemFontOfSize_(size))
    if color:
        field.setTextColor_(color)
    return field


def _make_checkbox(title: str, x: float, y: float, w: float = 340,
                   checked: bool = False, tooltip: str = "") -> NSButton:
    """Create a checkbox (NSSwitchButton) with optional tooltip."""
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h=22))
    btn.setButtonType_(3)  # NSSwitchButton
    btn.setTitle_(title)
    btn.setFont_(NSFont.systemFontOfSize_(13))
    btn.setState_(1 if checked else 0)
    if tooltip:
        btn.setToolTip_(tooltip)
    return btn


def _make_hint(text: str, x: float, y: float, w: float = 340) -> NSTextField:
    """Small secondary-color hint text below a control."""
    return _make_label(text, x, y, w, h=14, size=11,
                       color=NSColor.secondaryLabelColor())


# ---------------------------------------------------------------------------
# Preferences window — tabbed
# ---------------------------------------------------------------------------

TAB_W, TAB_H = 460, 440

# Tooltip strings — explain what each setting does + tradeoff
_TIP_RESULTS = (
    "How many notes to show per search.\n\n"
    "More results = broader coverage but slower synthesis.\n"
    "Fewer results = faster, more focused answers."
)
_TIP_MODE = (
    "Default search mode when you open the panel.\n\n"
    "Semantic: finds notes by meaning and theme — best for exploratory queries.\n"
    "Hybrid: blends meaning + exact words — good general-purpose default.\n"
    "Keyword: literal word matching only — fast, no API call, best when you remember exact phrasing."
)
_TIP_DEPTH = (
    "Controls how much meaning vs literal matching influences hybrid search.\n\n"
    "Low (Surface): prioritises exact word matches — fast, precise, but misses related notes.\n"
    "High (Deep): prioritises meaning and themes — finds thematic connections, but may surface "
    "loosely related notes."
)
_TIP_HYDE = (
    "Generates a hypothetical note excerpt before searching, so the embedding lands closer "
    "to how your actual notes are written.\n\n"
    "ON: dramatically better for reflective queries like 'what have I been thinking about grief?' "
    "Adds ~1 second and one GPT-4o-mini call per search.\n"
    "OFF: faster, uses your raw query as-is. Fine for specific lookups."
)
_TIP_PERSIST = (
    "Whether the search panel stays visible when another app takes focus.\n\n"
    "ON: panel stays open — useful for referencing notes while working in another app.\n"
    "OFF: panel hides when you click away — cleaner desktop, but you lose your place."
)
_TIP_SHORT = (
    "Filter out notes with very little content (a single word, a number, a one-line stub).\n\n"
    "ON: cleaner results — junk notes like '1' or stray phone numbers won't surface.\n"
    "OFF: every note is eligible — turn this off if you keep meaningful short notes."
)
_TIP_EXCLUDED = (
    "Folders listed here will never appear in search results.\n\n"
    "Useful for folders with other people's writing, receipts, bank statements, "
    "or anything you don't want surfacing in personal searches.\n"
    "One folder name per line. Names are case-sensitive."
)
_TIP_LOGIN = (
    "Start Writers Room automatically when you log in to your Mac.\n\n"
    "ON: always available in the menu bar without manual launch.\n"
    "OFF: you'll need to open the app manually each session."
)
_TIP_REINDEX = (
    "Re-read all notes from Apple Notes and rebuild the search index.\n\n"
    "Run this after adding, editing, or deleting notes so they appear in search. "
    "Takes 1–3 minutes depending on how many notes you have."
)


class PreferencesWindowController(NSWindowController):

    def _build_window(self) -> None:
        style = (
            NSTitledWindowMask
            | NSClosableWindowMask
            | NSMiniaturizableWindowMask
        )
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, TAB_W, TAB_H),
            style,
            NSBackingStoreBuffered,
            False,
        )
        win.setTitle_("Writers Room — Preferences")
        win.setLevel_(NSFloatingWindowLevel)
        win.center()
        self.setWindow_(win)

        content = win.contentView()

        # ── Tab view (leave 50px at bottom for Save button) ─────────
        BOTTOM = 50
        tabs = NSTabView.alloc().initWithFrame_(
            NSMakeRect(0, BOTTOM, TAB_W, TAB_H - BOTTOM)
        )

        tabs.addTabViewItem_(self._build_search_tab())
        tabs.addTabViewItem_(self._build_indexing_tab())
        tabs.addTabViewItem_(self._build_general_tab())
        content.addSubview_(tabs)

        # ── Save button (always visible, below tabs) ────────────────
        save_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(TAB_W - 100, 12, 80, 28)
        )
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_("saveClicked:")
        save_btn.setKeyEquivalent_("\r")  # Enter key = Save
        content.addSubview_(save_btn)

        # Register as delegate for windowWillClose auto-save
        win.setDelegate_(self)

    # ==================================================================
    # Tab 1 — Search
    # ==================================================================

    def _build_search_tab(self) -> NSTabViewItem:
        item = NSTabViewItem.alloc().initWithIdentifier_("search")
        item.setLabel_("Search")
        view = item.view()
        CW = TAB_W - 40   # content width
        y = 330

        # ── Results to show ──
        lbl = _make_label("Results to show:", 20, y)
        lbl.setToolTip_(_TIP_RESULTS)
        view.addSubview_(lbl)

        self._stepper = NSStepper.alloc().initWithFrame_(NSMakeRect(180, y - 2, 19, 24))
        self._stepper.setMinValue_(3)
        self._stepper.setMaxValue_(10)
        self._stepper.setIntValue_(self._prefs.n_results)
        self._stepper.setIncrement_(1)
        self._stepper.setTarget_(self)
        self._stepper.setAction_("stepperChanged:")
        self._stepper.setToolTip_(_TIP_RESULTS)
        view.addSubview_(self._stepper)

        self._count_label = _make_label(str(self._prefs.n_results), 206, y, w=30)
        view.addSubview_(self._count_label)

        y -= 50

        # ── Default mode ──
        lbl = _make_label("Default mode:", 20, y)
        lbl.setToolTip_(_TIP_MODE)
        view.addSubview_(lbl)

        self._mode_control = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(180, y - 2, 220, 26)
        )
        self._mode_control.setSegmentCount_(3)
        for i, label in enumerate(_MODE_LABELS):
            self._mode_control.setLabel_forSegment_(label, i)
        self._mode_control.setSegmentStyle_(NSSegmentStyleRounded)
        self._mode_control.setSelectedSegment_(
            _MODE_KEYS.index(self._prefs.default_mode)
        )
        self._mode_control.setToolTip_(_TIP_MODE)
        view.addSubview_(self._mode_control)

        y -= 56

        # ── Search depth slider ──
        lbl = _make_label("Search depth:", 20, y)
        lbl.setToolTip_(_TIP_DEPTH)
        view.addSubview_(lbl)

        self._depth_slider = NSSlider.alloc().initWithFrame_(
            NSMakeRect(180, y, 220, 24)
        )
        self._depth_slider.setMinValue_(0)
        self._depth_slider.setMaxValue_(100)
        self._depth_slider.setIntValue_(self._prefs.search_depth)
        self._depth_slider.setToolTip_(_TIP_DEPTH)
        self._depth_slider.setTarget_(self)
        self._depth_slider.setAction_("depthSliderChanged:")
        view.addSubview_(self._depth_slider)

        # Slider end labels
        view.addSubview_(_make_hint("Surface", 180, y - 16, w=60))
        view.addSubview_(_make_hint("Deep", 366, y - 16, w=40))

        # Current value label
        self._depth_value = _make_label(str(self._prefs.search_depth), 405, y, w=30)
        view.addSubview_(self._depth_value)

        y -= 54

        # ── HyDE ──
        self._hyde_checkbox = _make_checkbox(
            "Deep semantic search (HyDE)",
            20, y, checked=self._prefs.use_hyde, tooltip=_TIP_HYDE,
        )
        view.addSubview_(self._hyde_checkbox)

        view.addSubview_(_make_hint(
            "Generates a hypothetical note for richer matching. +1s latency per search.",
            40, y - 18, w=380,
        ))

        y -= 50

        # ── Persist window ──
        self._persist_checkbox = _make_checkbox(
            "Keep panel open when focus moves away",
            20, y, checked=self._prefs.persist_window, tooltip=_TIP_PERSIST,
        )
        view.addSubview_(self._persist_checkbox)

        return item

    # ==================================================================
    # Tab 2 — Indexing
    # ==================================================================

    def _build_indexing_tab(self) -> NSTabViewItem:
        item = NSTabViewItem.alloc().initWithIdentifier_("indexing")
        item.setLabel_("Indexing")
        view = item.view()
        y = 330

        # ── Skip short notes ──
        self._short_checkbox = _make_checkbox(
            "Skip short notes in search results",
            20, y, checked=self._prefs.skip_short_notes, tooltip=_TIP_SHORT,
        )
        view.addSubview_(self._short_checkbox)

        view.addSubview_(_make_hint(
            "Filters out notes with trivially short content (single words, stray numbers).",
            40, y - 18, w=380,
        ))

        y -= 56

        # ── Excluded folders ──
        lbl = _make_label("Excluded folders:", 20, y, bold=True)
        lbl.setToolTip_(_TIP_EXCLUDED)
        view.addSubview_(lbl)

        view.addSubview_(_make_hint(
            "One folder name per line. These folders won't appear in search.",
            20, y - 18, w=380,
        ))

        y -= 40

        # Scrollable text area for folder names
        scroll_h = 140
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(20, y - scroll_h + 20, TAB_W - 80, scroll_h)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(3)  # NSBezelBorder

        content_size = scroll.contentSize()
        self._folders_text = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, content_size.width, content_size.height)
        )
        self._folders_text.setMinSize_((0, content_size.height))
        self._folders_text.setMaxSize_((1e7, 1e7))
        self._folders_text.setVerticallyResizable_(True)
        self._folders_text.setHorizontallyResizable_(False)
        self._folders_text.textContainer().setWidthTracksTextView_(True)
        self._folders_text.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12, 0))
        self._folders_text.setToolTip_(_TIP_EXCLUDED)

        # Pre-fill with current excluded folders
        existing = self._prefs.excluded_folders
        if existing:
            self._folders_text.setString_("\n".join(existing))

        scroll.setDocumentView_(self._folders_text)
        view.addSubview_(scroll)

        y -= scroll_h + 20

        # ── Re-index button ──
        reindex_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 160, 28))
        reindex_btn.setTitle_("Re-index Notes")
        reindex_btn.setBezelStyle_(NSBezelStyleRounded)
        reindex_btn.setTarget_(self)
        reindex_btn.setAction_("reindexClicked:")
        reindex_btn.setToolTip_(_TIP_REINDEX)
        view.addSubview_(reindex_btn)

        self._status_label = _make_label("", 190, y + 4, w=200, size=11,
                                         color=NSColor.secondaryLabelColor())
        view.addSubview_(self._status_label)

        return item

    # ==================================================================
    # Tab 3 — General
    # ==================================================================

    def _build_general_tab(self) -> NSTabViewItem:
        item = NSTabViewItem.alloc().initWithIdentifier_("general")
        item.setLabel_("General")
        view = item.view()
        y = 330

        # ── Launch at login ──
        self._login_checkbox = _make_checkbox(
            "Launch Writers Room at login",
            20, y, checked=self._prefs.launch_at_login, tooltip=_TIP_LOGIN,
        )
        view.addSubview_(self._login_checkbox)

        view.addSubview_(_make_hint(
            "Adds a login item so Writers Room starts automatically with your Mac.",
            40, y - 18, w=380,
        ))

        return item

    # ==================================================================
    # Actions
    # ==================================================================

    @objc.IBAction
    def stepperChanged_(self, sender) -> None:
        self._count_label.setStringValue_(str(int(sender.intValue())))

    @objc.IBAction
    def depthSliderChanged_(self, sender) -> None:
        self._depth_value.setStringValue_(str(int(sender.intValue())))

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
        self._save_all()
        self.window().orderOut_(None)

    def _save_all(self) -> None:
        """Read all controls and persist to disk."""
        self._prefs.n_results       = int(self._stepper.intValue())
        self._prefs.default_mode    = _MODE_KEYS[self._mode_control.selectedSegment()]
        self._prefs.search_depth    = int(self._depth_slider.intValue())
        self._prefs.persist_window  = bool(self._persist_checkbox.state())
        self._prefs.use_hyde        = bool(self._hyde_checkbox.state())
        self._prefs.skip_short_notes = bool(self._short_checkbox.state())
        self._prefs.launch_at_login = bool(self._login_checkbox.state())

        # Excluded folders from text area
        raw = self._folders_text.string()
        folders = [line.strip() for line in raw.split("\n") if line.strip()]
        self._prefs.excluded_folders = folders

    def show(self) -> None:
        self.showWindow_(None)
        self.window().makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def windowWillClose_(self, notification) -> None:
        """Auto-save when the window is closed via the red button."""
        self._save_all()


# Module-level factory — avoids PyObjC intercepting classmethods on NSObject subclasses
def make_prefs_controller(prefs: Preferences, searcher) -> PreferencesWindowController:
    controller = PreferencesWindowController.alloc().init()
    controller._prefs         = prefs
    controller._searcher      = searcher
    controller._status_label  = None
    controller._stepper       = None
    controller._count_label   = None
    controller._mode_control  = None
    controller._depth_slider  = None
    controller._depth_value   = None
    controller._login_checkbox   = None
    controller._persist_checkbox = None
    controller._hyde_checkbox    = None
    controller._short_checkbox   = None
    controller._folders_text     = None
    controller._build_window()
    return controller
