"""
Writers Room — Search Panel

Raycast/Spotlight-style floating panel:
  ┌─────────────────────────────────────────────────────┐
  │  🔍  Search your notes...               [S] [H] [K] │
  ├─────────────────────────────────────────────────────┤
  │  Note Title                                  Folder │
  │  Snippet of content goes here...                    │
  ├─────────────────────────────────────────────────────┤
  │  ...                                                │
  └─────────────────────────────────────────────────────┘

Slash commands: /sm /hy /ky   ESC to close   Enter to open first result
"""

import subprocess
import threading
from typing import Callable

import objc
from utils import call_on_main
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSBezelStyleRegularSquare,
    NSBox,
    NSBoxSeparator,
    NSColor,
    NSFont,
    NSImage,
    NSImageView,
    NSMakeRect,
    NSObject,
    NSPanel,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentStyleCapsule,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSTextFieldCell,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectView,
)
from AppKit import (
    NSFloatingWindowLevel,
    NSViewWidthSizable,
    NSViewHeightSizable,
)
from Foundation import NSNotificationCenter

# ---------------------------------------------------------------------------
# NSPanel subclass — borderless, accepts keyboard input
# ---------------------------------------------------------------------------

class _KeyablePanel(NSPanel):
    def canBecomeKeyWindow(self):
        return True
    def canBecomeMainWindow(self):
        return False


# ---------------------------------------------------------------------------
# Visual effect material — prefer Menu material for native popover look
# ---------------------------------------------------------------------------

try:
    from AppKit import NSVisualEffectMaterialMenu
    _MATERIAL = NSVisualEffectMaterialMenu          # 5 — native macOS menu look
except ImportError:
    _MATERIAL = 5

try:
    from AppKit import NSVisualEffectStateActive
    _VEV_STATE = NSVisualEffectStateActive
except ImportError:
    _VEV_STATE = 1

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PANEL_W    = 620
SEARCH_H   = 56         # height of search bar area
SEP_H      = 1          # separator line
ROW_H      = 64.0       # height of each result row
CORNER_R   = 14.0       # panel corner radius

# Compute panel height: fixed at 5 rows (prefs can change result count but
# panel height is fixed — scroll handles overflow)
PANEL_H    = SEARCH_H + SEP_H + int(ROW_H * 5) + 8

# Mode control
_MODE_LABELS = ["Semantic", "Hybrid", "Keyword"]
_MODE_KEYS   = ["semantic", "hybrid", "keyword"]

_SLASH_COMMANDS = {
    "/sm": "semantic",
    "/hy": "hybrid",
    "/ky": "keyword",
}

DEBOUNCE_KEYWORD  = 0.15
DEBOUNCE_SEMANTIC = 0.40


# ---------------------------------------------------------------------------
# Helper — non-editable transparent label
# ---------------------------------------------------------------------------

def _label(text: str, x: float, y: float, w: float, h: float,
           size: float = 13, color=None, bold: bool = False) -> NSTextField:
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    f.setStringValue_(text)
    f.setEditable_(False)
    f.setBordered_(False)
    f.setDrawsBackground_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color:
        f.setTextColor_(color)
    f.setLineBreakMode_(3)   # NSLineBreakByTruncatingTail
    return f


# ---------------------------------------------------------------------------
# NSTextField delegate — live typing, ESC, Enter
# ---------------------------------------------------------------------------

class _QueryDelegate(NSObject):

    def init(self):
        self = objc.super(_QueryDelegate, self).init()
        self.on_change:     Callable[[str], None] | None = None
        self.on_escape:     Callable[[], None]    | None = None
        self.on_enter_first: Callable[[], None]   | None = None
        return self

    def controlTextDidChange_(self, notification) -> None:
        if self.on_change:
            self.on_change(notification.object().stringValue())

    def control_textView_doCommandBySelector_(self, ctrl, tv, sel) -> bool:
        if sel == "cancelOperation:":
            if self.on_escape:
                self.on_escape()
            return True
        if sel == "insertNewline:":
            if self.on_enter_first:
                self.on_enter_first()
            return True
        return False


# ---------------------------------------------------------------------------
# NSTableView data source + delegate
# ---------------------------------------------------------------------------

class _ResultsDataSource(NSObject):

    def init(self):
        self = objc.super(_ResultsDataSource, self).init()
        self._results: list[dict] = []
        self.on_open: Callable[[dict], None] | None = None
        return self

    def set_results(self, results: list[dict]) -> None:
        self._results = results

    def results(self) -> list[dict]:
        return self._results

    # NSTableViewDataSource
    def numberOfRowsInTableView_(self, tv) -> int:
        return len(self._results)

    def tableView_objectValueForTableColumn_row_(self, tv, col, row):
        return None  # view-based table

    # NSTableViewDelegate
    def tableView_viewForTableColumn_row_(self, tv, col, row):
        identifier = "WRCell"
        cell = tv.makeViewWithIdentifier_owner_(identifier, self)
        if cell is None:
            cell = _ResultCell.alloc().initWithFrame_(
                NSMakeRect(0, 0, PANEL_W, ROW_H)
            )
            cell.setIdentifier_(identifier)
        cell.setResult_(self._results[row])
        return cell

    def tableView_heightOfRow_(self, tv, row) -> float:
        return ROW_H

    def tableViewSelectionDidChange_(self, notification) -> None:
        tv  = notification.object()
        row = tv.selectedRow()
        if 0 <= row < len(self._results) and self.on_open:
            result = self._results[row]
            tv.deselectAll_(None)
            self.on_open(result)


# ---------------------------------------------------------------------------
# Result cell — title + snippet (left) · folder (right)
# ---------------------------------------------------------------------------

_TITLE_FONT   = NSFont.systemFontOfSize_weight_(15, 0.4)   # medium weight
_SNIPPET_FONT = NSFont.systemFontOfSize_(12)
_FOLDER_FONT  = NSFont.systemFontOfSize_(11)

FOLDER_W  = 110   # right-aligned folder chip width
INNER_PAD = 16    # left/right inner padding


class _ResultCell(NSView):

    def initWithFrame_(self, frame):
        self = objc.super(_ResultCell, self).initWithFrame_(frame)
        W = PANEL_W

        # Title — left side, leaves room for folder chip on right
        self._title = _label(
            "", INNER_PAD, ROW_H - 28, W - FOLDER_W - INNER_PAD * 2 - 8, 19,
            size=15, bold=False,
        )
        self._title.setFont_(_TITLE_FONT)
        self.addSubview_(self._title)

        # Folder chip — right side, same baseline as title
        self._folder = _label(
            "", W - FOLDER_W - INNER_PAD, ROW_H - 28, FOLDER_W, 19,
            size=11, color=NSColor.tertiaryLabelColor(),
        )
        self._folder.setAlignment_(2)  # NSTextAlignmentRight
        self.addSubview_(self._folder)

        # Snippet — below title, full width minus padding
        self._snippet = _label(
            "", INNER_PAD, 10, W - INNER_PAD * 2, 17,
            size=12, color=NSColor.secondaryLabelColor(),
        )
        self.addSubview_(self._snippet)

        return self

    def setResult_(self, result: dict) -> None:
        self._title.setStringValue_(result.get("title", ""))
        self._folder.setStringValue_(result.get("folder", ""))
        self._snippet.setStringValue_(result.get("snippet", ""))


# ---------------------------------------------------------------------------
# Main search panel
# ---------------------------------------------------------------------------

class SearchPanel:

    def __init__(self, searcher, prefs) -> None:
        self._searcher = searcher
        self._prefs    = prefs

        self._panel:         _KeyablePanel | None    = None
        self._query_field:   NSTextField   | None    = None
        self._mode_control:  NSSegmentedControl | None = None
        self._table_view:    NSTableView   | None    = None
        self._data_source:   _ResultsDataSource | None = None
        self._count_label:   NSTextField   | None    = None
        self._delegate:      _QueryDelegate | None   = None

        self._current_mode:    str                   = prefs.default_mode
        self._debounce_timer:  threading.Timer | None = None

        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        W, H = PANEL_W, PANEL_H

        # ── Panel ────────────────────────────────────────────────────
        self._panel = _KeyablePanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), 0, NSBackingStoreBuffered, False,
        )
        self._panel.setLevel_(NSFloatingWindowLevel)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.center()

        content = self._panel.contentView()

        # ── Frosted glass background ─────────────────────────────────
        vev = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        vev.setMaterial_(_MATERIAL)
        vev.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        vev.setState_(_VEV_STATE)
        vev.setWantsLayer_(True)
        vev.layer().setCornerRadius_(CORNER_R)
        vev.layer().setMasksToBounds_(True)
        vev.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        content.addSubview_(vev)

        # ── Search bar row ───────────────────────────────────────────
        # Magnifying glass SF Symbol icon
        search_icon = NSImageView.alloc().initWithFrame_(
            NSMakeRect(14, H - SEARCH_H + 17, 22, 22)
        )
        sf_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "magnifyingglass", "Search"
        )
        if sf_img:
            search_icon.setImage_(sf_img)
            search_icon.setContentTintColor_(NSColor.tertiaryLabelColor())
        content.addSubview_(search_icon)

        # Search text field — no bezel, large font
        FIELD_L = 44            # left edge (after icon)
        MODE_W  = 175           # mode control width
        FIELD_R = W - MODE_W - 12  # right edge
        FIELD_H = 30

        self._query_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_L, H - SEARCH_H + 13, FIELD_R - FIELD_L, FIELD_H)
        )
        self._query_field.setPlaceholderString_("Search your notes…")
        self._query_field.setFont_(NSFont.systemFontOfSize_(16))
        self._query_field.setBezeled_(False)
        self._query_field.setDrawsBackground_(False)
        self._query_field.setEditable_(True)
        self._query_field.setFocusRingType_(1)   # none

        self._delegate = _QueryDelegate.alloc().init()
        self._delegate.on_change      = self._on_query_changed
        self._delegate.on_escape      = self.hide
        self._delegate.on_enter_first = self._open_first_result
        self._query_field.setDelegate_(self._delegate)
        content.addSubview_(self._query_field)

        # Mode segmented control — right side of search bar
        self._mode_control = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(W - MODE_W - 10, H - SEARCH_H + 15, MODE_W, 26)
        )
        self._mode_control.setSegmentCount_(3)
        for i, label in enumerate(_MODE_LABELS):
            self._mode_control.setLabel_forSegment_(label, i)
        self._mode_control.setSegmentStyle_(NSSegmentStyleCapsule)
        self._mode_control.setSelectedSegment_(_MODE_KEYS.index(self._current_mode))
        self._mode_control.setTarget_(self)
        self._mode_control.setAction_("modeChanged:")
        self._mode_control.setFont_(NSFont.systemFontOfSize_(11))
        content.addSubview_(self._mode_control)

        # ── Separator line ───────────────────────────────────────────
        sep = NSBox.alloc().initWithFrame_(
            NSMakeRect(0, H - SEARCH_H, W, SEP_H)
        )
        sep.setBoxType_(2)   # NSBoxSeparator
        content.addSubview_(sep)

        # ── Count / status label (bottom-right of search bar) ────────
        self._count_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_L, H - SEARCH_H + 2, FIELD_R - FIELD_L, 11)
        )
        self._count_label.setStringValue_("")
        self._count_label.setEditable_(False)
        self._count_label.setBordered_(False)
        self._count_label.setDrawsBackground_(False)
        self._count_label.setFont_(NSFont.systemFontOfSize_(9))
        self._count_label.setTextColor_(NSColor.quaternaryLabelColor())
        content.addSubview_(self._count_label)

        # ── Results table ────────────────────────────────────────────
        table_h = H - SEARCH_H - SEP_H

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, table_h)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)

        self._table_view = NSTableView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, table_h)
        )
        self._table_view.setRowHeight_(ROW_H)
        self._table_view.setUsesAlternatingRowBackgroundColors_(False)
        self._table_view.setHeaderView_(None)
        self._table_view.setGridStyleMask_(0)
        self._table_view.setSelectionHighlightStyle_(1)
        self._table_view.setBackgroundColor_(NSColor.clearColor())
        self._table_view.setIntercellSpacing_(NSMakeRect(0, 0, 0, 0).size)

        col = NSTableColumn.alloc().initWithIdentifier_("result")
        col.setWidth_(W)
        col.setResizingMask_(1)
        self._table_view.addTableColumn_(col)

        self._data_source = _ResultsDataSource.alloc().init()
        self._data_source.on_open = self._open_note
        self._table_view.setDataSource_(self._data_source)
        self._table_view.setDelegate_(self._data_source)

        scroll.setDocumentView_(self._table_view)
        content.addSubview_(scroll)

    # ------------------------------------------------------------------
    # Show / hide / toggle
    # ------------------------------------------------------------------

    def show(self) -> None:
        NSApp.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)
        self._panel.makeFirstResponder_(self._query_field)

    def hide(self) -> None:
        self._panel.orderOut_(None)

    def toggle(self) -> None:
        if self._panel.isVisible():
            self.hide()
        else:
            self.show()

    # ------------------------------------------------------------------
    # Mode control
    # ------------------------------------------------------------------

    @objc.IBAction
    def modeChanged_(self, sender) -> None:
        self._current_mode = _MODE_KEYS[sender.selectedSegment()]
        query = self._query_field.stringValue().strip()
        if query:
            self._trigger_search(query)

    # ------------------------------------------------------------------
    # Query input
    # ------------------------------------------------------------------

    def _on_query_changed(self, text: str) -> None:
        lower = text.strip().lower()

        # Slash command detection
        for prefix, mode in _SLASH_COMMANDS.items():
            if lower.startswith(prefix):
                remainder = text[len(prefix):].lstrip()
                self._set_mode(mode)
                self._query_field.setStringValue_(remainder)
                text = remainder
                break

        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None

        stripped = text.strip()
        if not stripped:
            self._set_results([])
            self._count_label.setStringValue_("")
            return

        self._trigger_search(stripped)

    def _trigger_search(self, query: str) -> None:
        if self._debounce_timer:
            self._debounce_timer.cancel()
        delay = DEBOUNCE_KEYWORD if self._current_mode == "keyword" else DEBOUNCE_SEMANTIC
        self._debounce_timer = threading.Timer(delay, self._run_search_bg, args=[query])
        self._debounce_timer.daemon = True
        self._debounce_timer.start()
        if self._current_mode != "keyword":
            call_on_main(lambda: self._count_label.setStringValue_("searching…"))

    def _set_mode(self, mode: str) -> None:
        if mode in _MODE_KEYS:
            self._current_mode = mode
            idx = _MODE_KEYS.index(mode)
            call_on_main(lambda: self._mode_control.setSelectedSegment_(idx))

    # ------------------------------------------------------------------
    # Search (background thread)
    # ------------------------------------------------------------------

    def _run_search_bg(self, query: str) -> None:
        n    = self._prefs.n_results
        mode = self._current_mode
        try:
            results = self._searcher.search(query, n=n, mode=mode)
        except Exception as e:
            err = str(e)
            call_on_main(lambda: self._count_label.setStringValue_(f"error: {err}"))
            return

        n_found    = len(results)
        count_text = f"{n_found} result{'s' if n_found != 1 else ''}"
        call_on_main(lambda: self._count_label.setStringValue_(count_text))
        call_on_main(lambda: self._set_results(results))

    def _set_results(self, results: list[dict]) -> None:
        self._data_source.set_results(results)
        self._table_view.reloadData()

    # ------------------------------------------------------------------
    # Open note
    # ------------------------------------------------------------------

    def _open_first_result(self) -> None:
        results = self._data_source.results()
        if results:
            self._open_note(results[0])

    def _open_note(self, result: dict) -> None:
        title  = result["title"].replace("\\", "\\\\").replace('"', '\\"')
        folder = result["folder"].replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'tell application "Notes" '
            f'to show (first note of folder "{folder}" whose name is "{title}")'
        )
        subprocess.Popen(["osascript", "-e", script])
