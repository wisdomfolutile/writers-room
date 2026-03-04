"""
Writers Room — Search Panel

Floating NSPanel with:
  - NSTextField for query input (with live debounce)
  - NSSegmentedControl for mode switching (Semantic / Hybrid / Keyword)
  - NSTableView for results (5 rows by default)
  - Slash commands: /sm /hy /ky
  - Single-click row → AppleScript opens note in Apple Notes
  - ESC → hide panel
"""

import subprocess
import threading
from typing import Callable

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSMakeRect,
    NSNonactivatingPanelMask,
    NSObject,
    NSPanel,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentedStyleRounded,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectView,
)
from AppKit import NSFloatingWindowLevel
from Foundation import NSMakeSize, NSNotificationCenter

try:
    from AppKit import NSVisualEffectMaterialPopover
    _MATERIAL = NSVisualEffectMaterialPopover
except ImportError:
    _MATERIAL = 14   # NSVisualEffectMaterialPopover raw value fallback

try:
    from AppKit import NSVisualEffectStateActive
    _VEV_STATE = NSVisualEffectStateActive
except ImportError:
    _VEV_STATE = 1

# Mode mapping
_MODE_LABELS = ["Semantic", "Hybrid", "Keyword"]
_MODE_KEYS   = ["semantic", "hybrid", "keyword"]

# Slash commands
_SLASH_COMMANDS = {
    "/sm": "semantic",
    "/hy": "hybrid",
    "/ky": "keyword",
}

DEBOUNCE_KEYWORD  = 0.15   # seconds
DEBOUNCE_SEMANTIC = 0.40   # seconds

PANEL_WIDTH  = 560
PANEL_HEIGHT = 440
ROW_HEIGHT   = 52.0


# ---------------------------------------------------------------------------
# NSTextField delegate — live typing + ESC
# ---------------------------------------------------------------------------

class QueryFieldDelegate(NSObject):

    def init(self):
        self = objc.super(QueryFieldDelegate, self).init()
        self.on_change: Callable[[str], None] | None = None
        self.on_escape: Callable[[], None] | None = None
        return self

    def controlTextDidChange_(self, notification) -> None:
        text = notification.object().stringValue()
        if self.on_change:
            self.on_change(text)

    def control_textView_doCommandBySelector_(self, control, tv, selector) -> bool:
        if selector == "cancelOperation:":
            if self.on_escape:
                self.on_escape()
            return True
        if selector == "insertNewline:":
            # Treat Enter as: open first result
            if self.on_escape:
                # reuse first-result-open logic via a separate callback if needed
                pass
            return False
        return False


# ---------------------------------------------------------------------------
# NSTableView data source + delegate
# ---------------------------------------------------------------------------

class ResultsDataSource(NSObject):

    def init(self):
        self = objc.super(ResultsDataSource, self).init()
        self._results: list[dict] = []
        self.on_select: Callable[[dict], None] | None = None
        return self

    def set_results(self, results: list[dict]) -> None:
        self._results = results

    # NSTableViewDataSource

    def numberOfRowsInTableView_(self, table_view) -> int:
        return len(self._results)

    def tableView_objectValueForTableColumn_row_(self, tv, col, row):
        return None   # we use view-based cells via tableView_viewForTableColumn_row_

    # NSTableViewDelegate

    def tableView_viewForTableColumn_row_(self, tv, col, row):
        result = self._results[row]
        identifier = "WRResultCell"

        cell_view = tv.makeViewWithIdentifier_owner_(identifier, self)
        if cell_view is None:
            cell_view = _ResultCellView.alloc().initWithFrame_(
                NSMakeRect(0, 0, PANEL_WIDTH, ROW_HEIGHT)
            )
            cell_view.setIdentifier_(identifier)

        cell_view.set_result(result)
        return cell_view

    def tableView_heightOfRow_(self, tv, row) -> float:
        return ROW_HEIGHT

    def tableViewSelectionDidChange_(self, notification) -> None:
        tv  = notification.object()
        row = tv.selectedRow()
        if row >= 0 and row < len(self._results) and self.on_select:
            self.on_select(self._results[row])
            # Deselect immediately so the row doesn't stay highlighted
            tv.deselectAll_(None)


# ---------------------------------------------------------------------------
# Custom cell view — title + folder · snippet
# ---------------------------------------------------------------------------

class _ResultCellView(NSView):

    def initWithFrame_(self, frame):
        self = objc.super(_ResultCellView, self).initWithFrame_(frame)

        # Title label (bold, size 13)
        self._title_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, ROW_HEIGHT - 26, PANEL_WIDTH - 24, 18)
        )
        self._title_field.setEditable_(False)
        self._title_field.setBordered_(False)
        self._title_field.setDrawsBackground_(False)
        self._title_field.setFont_(NSFont.boldSystemFontOfSize_(13))
        self._title_field.setLineBreakMode_(3)   # NSLineBreakByTruncatingTail
        self.addSubview_(self._title_field)

        # Subtitle label (regular, size 11, secondary color)
        self._sub_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, 8, PANEL_WIDTH - 24, 16)
        )
        self._sub_field.setEditable_(False)
        self._sub_field.setBordered_(False)
        self._sub_field.setDrawsBackground_(False)
        self._sub_field.setFont_(NSFont.systemFontOfSize_(11))
        self._sub_field.setTextColor_(NSColor.secondaryLabelColor())
        self._sub_field.setLineBreakMode_(3)
        self.addSubview_(self._sub_field)

        return self

    def set_result(self, result: dict) -> None:
        self._title_field.setStringValue_(result.get("title", ""))
        folder  = result.get("folder", "")
        snippet = result.get("snippet", "")
        self._sub_field.setStringValue_(f"{folder}  ·  {snippet}")


# ---------------------------------------------------------------------------
# Main search panel
# ---------------------------------------------------------------------------

class SearchPanel:

    def __init__(self, searcher, prefs) -> None:
        self._searcher = searcher
        self._prefs    = prefs

        self._panel: NSPanel | None = None
        self._query_field: NSTextField | None = None
        self._mode_control: NSSegmentedControl | None = None
        self._table_view: NSTableView | None = None
        self._data_source: ResultsDataSource | None = None
        self._status_label: NSTextField | None = None

        self._field_delegate: QueryFieldDelegate | None = None

        self._current_mode: str = prefs.default_mode
        self._debounce_timer: threading.Timer | None = None

        self._build()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build(self) -> None:
        W, H = PANEL_WIDTH, PANEL_HEIGHT

        # --- Panel ---
        style = NSNonactivatingPanelMask | 0  # borderless
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setLevel_(NSFloatingWindowLevel)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.center()

        content = self._panel.contentView()

        # --- Frosted glass background ---
        vev = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        vev.setMaterial_(_MATERIAL)
        vev.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        vev.setState_(_VEV_STATE)
        vev.setWantsLayer_(True)
        vev.layer().setCornerRadius_(12.0)
        vev.setAutoresizingMask_(18)   # width + height sizable
        content.addSubview_(vev)

        # --- Query text field ---
        self._query_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, H - 48, W - 24, 34)
        )
        self._query_field.setPlaceholderString_("Search notes…   /sm · /hy · /ky to switch mode")
        self._query_field.setFont_(NSFont.systemFontOfSize_(14))
        self._query_field.setBezeled_(True)
        self._query_field.setEditable_(True)
        self._query_field.setFocusRingType_(1)   # NSFocusRingTypeNone

        self._field_delegate = QueryFieldDelegate.alloc().init()
        self._field_delegate.on_change = self._on_query_changed
        self._field_delegate.on_escape = self.hide
        self._query_field.setDelegate_(self._field_delegate)

        content.addSubview_(self._query_field)

        # --- Mode segmented control ---
        self._mode_control = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(12, H - 84, 240, 26)
        )
        self._mode_control.setSegmentCount_(3)
        for i, label in enumerate(_MODE_LABELS):
            self._mode_control.setLabel_forSegment_(label, i)
        self._mode_control.setSegmentStyle_(NSSegmentedStyleRounded)
        self._mode_control.setSelectedSegment_(_MODE_KEYS.index(self._current_mode))
        self._mode_control.setTarget_(self)
        self._mode_control.setAction_("modeChanged:")
        content.addSubview_(self._mode_control)

        # --- Status label ---
        self._status_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(260, H - 82, W - 272, 20)
        )
        self._status_label.setStringValue_("")
        self._status_label.setEditable_(False)
        self._status_label.setBordered_(False)
        self._status_label.setDrawsBackground_(False)
        self._status_label.setFont_(NSFont.systemFontOfSize_(11))
        self._status_label.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(self._status_label)

        # --- Results table ---
        table_y = 0
        table_h = H - 96

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, table_y, W, table_h)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)

        self._table_view = NSTableView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, table_h)
        )
        self._table_view.setRowHeight_(ROW_HEIGHT)
        self._table_view.setUsesAlternatingRowBackgroundColors_(False)
        self._table_view.setHeaderView_(None)
        self._table_view.setGridStyleMask_(0)   # no grid lines
        self._table_view.setSelectionHighlightStyle_(1)   # NSTableViewSelectionHighlightStyleRegular
        self._table_view.setBackgroundColor_(NSColor.clearColor())

        col = NSTableColumn.alloc().initWithIdentifier_("result")
        col.setWidth_(W)
        col.setResizingMask_(1)   # NSTableColumnAutoresizingMask
        self._table_view.addTableColumn_(col)

        self._data_source = ResultsDataSource.alloc().init()
        self._data_source.on_select = self._open_note
        self._table_view.setDataSource_(self._data_source)
        self._table_view.setDelegate_(self._data_source)

        scroll.setDocumentView_(self._table_view)
        content.addSubview_(scroll)

    # ------------------------------------------------------------------
    # Show / hide
    # ------------------------------------------------------------------

    def show(self) -> None:
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
    # Mode control action
    # ------------------------------------------------------------------

    @objc.IBAction
    def modeChanged_(self, sender) -> None:
        self._current_mode = _MODE_KEYS[sender.selectedSegment()]
        # Re-run search with new mode if there's a query
        query = self._query_field.stringValue().strip()
        if query:
            self._trigger_search(query)

    # ------------------------------------------------------------------
    # Query change handler + slash commands
    # ------------------------------------------------------------------

    def _on_query_changed(self, text: str) -> None:
        lower = text.strip().lower()

        # Detect slash commands
        for prefix, mode in _SLASH_COMMANDS.items():
            if lower.startswith(prefix):
                remainder = text[len(prefix):].lstrip()
                self._set_mode(mode)
                self._query_field.setStringValue_(remainder)
                text = remainder
                break

        # Cancel existing debounce
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None

        stripped = text.strip()
        if not stripped:
            self._set_results([])
            self._status_label.setStringValue_("")
            return

        self._trigger_search(stripped)

    def _trigger_search(self, query: str) -> None:
        """Start a debounced search for query."""
        if self._debounce_timer:
            self._debounce_timer.cancel()

        delay = DEBOUNCE_KEYWORD if self._current_mode == "keyword" else DEBOUNCE_SEMANTIC
        self._debounce_timer = threading.Timer(delay, self._run_search_bg, args=[query])
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

        if self._current_mode != "keyword":
            objc.callAfter(self._status_label.setStringValue_, "Searching…")

    def _set_mode(self, mode: str) -> None:
        if mode in _MODE_KEYS:
            self._current_mode = mode
            idx = _MODE_KEYS.index(mode)
            objc.callAfter(self._mode_control.setSelectedSegment_, idx)

    # ------------------------------------------------------------------
    # Background search
    # ------------------------------------------------------------------

    def _run_search_bg(self, query: str) -> None:
        """Runs on a background thread. Posts results to main thread."""
        n    = self._prefs.n_results
        mode = self._current_mode
        try:
            results = self._searcher.search(query, n=n, mode=mode)
        except Exception as e:
            objc.callAfter(self._status_label.setStringValue_, f"Error: {e}")
            return

        count_text = f"{len(results)} result{'s' if len(results) != 1 else ''}"
        objc.callAfter(self._status_label.setStringValue_, count_text)
        objc.callAfter(self._set_results, results)

    def _set_results(self, results: list[dict]) -> None:
        """Must be called on the main thread."""
        self._data_source.set_results(results)
        self._table_view.reloadData()

    # ------------------------------------------------------------------
    # Open note via AppleScript
    # ------------------------------------------------------------------

    def _open_note(self, result: dict) -> None:
        """Fire-and-forget AppleScript call. Panel stays visible."""
        title  = result["title"].replace("\\", "\\\\").replace('"', '\\"')
        folder = result["folder"].replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'tell application "Notes" '
            f'to show (first note of folder "{folder}" whose name is "{title}")'
        )
        subprocess.Popen(["osascript", "-e", script])
