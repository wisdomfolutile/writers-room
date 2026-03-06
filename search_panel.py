"""
Writers Room 2.0 — Search Panel

Raycast/Spotlight-style floating panel with second-brain companion mode:

  ┌────────────────────────────────────────────────────────┐
  │  🔍  What have I been circling about grief...? [S][H][K]│
  ├────────────────────────────────────────────────────────┤
  │  You've been returning to grief in cycles—             │
  │  especially in [[Elegy for Tuesday]] and               │  ← synthesis
  │  [[The Weight of Almost]]. Both feel unfinished...     │
  ├────────────────────────────────────────────────────────┤
  │  Note Title                       Ideas    ↗          │
  │  snippet of content…                                   │  ← result rows
  └────────────────────────────────────────────────────────┘

Note titles in [[brackets]] are clickable teal links → open in Apple Notes.
↗ icon button on every row also opens the note directly.

Slash commands: /sm /hy /ky   ESC to close   Enter to open first result
"""

import random
import re
import subprocess
import threading
from typing import Callable
from urllib.parse import quote, unquote

import objc
from utils import call_on_main
from AppKit import (
    NSApp,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSButton,
    NSBox,
    NSBoxSeparator,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSBackgroundColorAttributeName,
    NSImage,
    NSImageView,
    NSLinkAttributeName,
    NSMakeRect,
    NSMutableAttributedString,
    NSMutableParagraphStyle,
    NSObject,
    NSPanel,
    NSParagraphStyleAttributeName,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentStyleCapsule,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSTextView,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectView,
)
from AppKit import (
    NSFloatingWindowLevel,
    NSViewWidthSizable,
    NSViewHeightSizable,
)
from Foundation import NSNotificationCenter, NSURL

# ---------------------------------------------------------------------------
# NSPanel subclass — borderless, accepts keyboard input
# ---------------------------------------------------------------------------

class _KeyablePanel(NSPanel):
    def canBecomeKeyWindow(self):
        return True
    def canBecomeMainWindow(self):
        return False


# ---------------------------------------------------------------------------
# Visual effect material
# ---------------------------------------------------------------------------

try:
    from AppKit import NSVisualEffectMaterialMenu
    _MATERIAL = NSVisualEffectMaterialMenu
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

PANEL_W   = 620
SEARCH_H  = 56          # search bar height
SEP_H     = 1           # separator below search bar
ANSWER_H  = 130         # synthesis text area
SEP2_H    = 1           # separator between synthesis and results
ROW_H     = 64.0        # result row height
CORNER_R  = 16.0        # panel corner radius

# Total height: search bar + answer area + 5 result rows + small footer
PANEL_H = SEARCH_H + SEP_H + ANSWER_H + SEP2_H + int(ROW_H * 5) + 8  # = 516

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

# Evocative placeholder hints — one is chosen at random each time the panel opens
_PLACEHOLDERS = [
    "What have I been circling about grief without finishing?",
    "What ideas keep returning to me?",
    "What have I written most about this past year?",
    "Where does my thinking on identity lead?",
    "What am I afraid to write about directly?",
    "Which themes run through my recent work?",
    "What patterns am I not seeing in my own writing?",
    "What have I abandoned that deserves another look?",
]

FOLDER_W  = 100   # folder chip width
INNER_PAD = 16    # left/right inner padding
OPEN_BTN_W = 22   # ↗ icon button width
OPEN_BTN_X = PANEL_W - INNER_PAD - OPEN_BTN_W  # = 582


# ---------------------------------------------------------------------------
# Claude brand accent — #E97133 (warm orange)
# ---------------------------------------------------------------------------

def _accent() -> NSColor:
    """Claude orange. Used for interactive elements and note reference chips."""
    return NSColor.colorWithSRGBRed_green_blue_alpha_(0.914, 0.443, 0.200, 1.0)


# ---------------------------------------------------------------------------
# Folder chip — code-chip style (monospace + subtle rounded background)
# ---------------------------------------------------------------------------

class _FolderChip(NSView):
    """
    A folder name rendered as an inline code chip — like Claude's `server.py`
    inline code style: SF Mono, subtle rounded-rect background that adapts
    to light/dark mode via drawRect_ (no layer CGColor dance needed).
    """

    def initWithFrame_(self, frame):
        self = objc.super(_FolderChip, self).initWithFrame_(frame)
        if self is None:
            return None
        W, H = frame.size.width, frame.size.height
        self._label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(6, 2, W - 12, H - 4)
        )
        self._label.setEditable_(False)
        self._label.setBordered_(False)
        self._label.setDrawsBackground_(False)
        self._label.setFont_(NSFont.monospacedSystemFontOfSize_(10, 0))
        self._label.setTextColor_(NSColor.secondaryLabelColor())
        self._label.setAlignment_(1)   # NSTextAlignmentCenter
        self._label.setLineBreakMode_(3)
        self.addSubview_(self._label)
        return self

    def drawRect_(self, rect) -> None:
        NSColor.labelColor().colorWithAlphaComponent_(0.07).set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 5.0, 5.0
        ).fill()

    def setFolder_(self, name: str) -> None:
        self._label.setStringValue_(name)


def _make_folder_chip(x: float, y: float, w: float, h: float) -> _FolderChip:
    return _FolderChip.alloc().initWithFrame_(NSMakeRect(x, y, w, h))


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
# Attributed string builder — parses [[Note Title]] → clickable teal links
# ---------------------------------------------------------------------------

def _make_answer_attr_string(text: str, secondary: bool = False) -> NSMutableAttributedString:
    """
    Parse [[Note Title]] patterns from synthesis text and build an
    NSMutableAttributedString where:
    - plain text: system 14pt in labelColor / secondaryLabelColor, 4pt line spacing
    - [[Note Title]] → Claude-style orange chip: accent text + 12% orange background fill,
      clickable via NSLinkAttributeName so _AnswerDelegate can intercept
    """
    base_color = NSColor.secondaryLabelColor() if secondary else NSColor.labelColor()
    base_font  = NSFont.systemFontOfSize_(14)

    # Line spacing shared across all paragraphs — Claude-like breathing room
    para = NSMutableParagraphStyle.alloc().init()
    para.setLineSpacing_(4.0)

    result = NSMutableAttributedString.alloc().initWithString_("")

    base_attrs: dict = {
        NSFontAttributeName: base_font,
        NSForegroundColorAttributeName: base_color,
        NSParagraphStyleAttributeName: para,
    }

    pos = 0
    for m in re.finditer(r'\[\[(.+?)\]\]', text):
        # Plain text before the match
        before = text[pos:m.start()]
        if before:
            chunk = NSAttributedString.alloc().initWithString_attributes_(before, base_attrs)
            result.appendAttributedString_(chunk)

        # Note title as a Claude-style orange code chip + clickable link
        note_title = m.group(1)
        url = NSURL.URLWithString_(f"writersroom://{quote(note_title)}")
        link_attrs: dict = {
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(13, 0.3),
            NSForegroundColorAttributeName: _accent(),
            NSBackgroundColorAttributeName: _accent().colorWithAlphaComponent_(0.12),
            NSLinkAttributeName: url,
            NSParagraphStyleAttributeName: para,
        }
        linked = NSAttributedString.alloc().initWithString_attributes_(note_title, link_attrs)
        result.appendAttributedString_(linked)

        pos = m.end()

    # Remaining plain text
    remaining = text[pos:]
    if remaining:
        chunk = NSAttributedString.alloc().initWithString_attributes_(remaining, base_attrs)
        result.appendAttributedString_(chunk)

    return result


# ---------------------------------------------------------------------------
# NSTextView delegate — handles [[Note Title]] link clicks in answer area
# ---------------------------------------------------------------------------

class _AnswerDelegate(NSObject):

    def init(self):
        self = objc.super(_AnswerDelegate, self).init()
        if self is None:
            return None
        self._on_link_click: Callable[[str], None] | None = None
        return self

    def textView_clickedOnLink_atIndex_(self, tv, link, idx) -> bool:
        if self._on_link_click is None:
            return False
        url_str = (
            str(link.absoluteString())
            if hasattr(link, "absoluteString")
            else str(link)
        )
        if url_str.startswith("writersroom://"):
            note_title = unquote(url_str[len("writersroom://"):])
            self._on_link_click(note_title)
            return True
        return False


# ---------------------------------------------------------------------------
# NSTextField delegate — live typing, ESC, Enter
# ---------------------------------------------------------------------------

class _QueryDelegate(NSObject):

    def init(self):
        self = objc.super(_QueryDelegate, self).init()
        self.on_change:      Callable[[str], None] | None = None
        self.on_escape:      Callable[[], None]    | None = None
        self.on_enter_first: Callable[[], None]    | None = None
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
        # Refresh callback on every create/reuse so it never goes stale
        cell._open_callback = self.on_open
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
# Result cell — title + snippet (left) · folder · ↗ button (right)
# ---------------------------------------------------------------------------

_TITLE_FONT   = NSFont.systemFontOfSize_weight_(15, 0.4)   # medium weight
_SNIPPET_FONT = NSFont.systemFontOfSize_(12)
_FOLDER_FONT  = NSFont.systemFontOfSize_(11)


class _ResultCell(NSView):

    def initWithFrame_(self, frame):
        self = objc.super(_ResultCell, self).initWithFrame_(frame)
        if self is None:
            return None

        self._open_callback: Callable[[dict], None] | None = None
        self._result: dict | None = None

        W = PANEL_W

        # ── Title — left side, leaves room for folder + ↗ button
        # Available right edge before folder: OPEN_BTN_X - FOLDER_W - 8 = 582 - 100 - 8 = 474
        # Title width = 474 - INNER_PAD = 474 - 16 = 458
        self._title = _label(
            "", INNER_PAD, ROW_H - 28, 458, 19,
            size=15, bold=False,
        )
        self._title.setFont_(_TITLE_FONT)
        self.addSubview_(self._title)

        # ── Folder chip — code-chip style, right of title, left of ↗ button
        # x = OPEN_BTN_X - FOLDER_W - 8 = 582 - 100 - 8 = 474
        # Height 22 so the chip has 2px padding above/below the 18px text baseline
        self._folder = _make_folder_chip(474, ROW_H - 30, FOLDER_W, 22)
        self.addSubview_(self._folder)

        # ── Snippet — below title, full width minus padding
        self._snippet = _label(
            "", INNER_PAD, 10, W - INNER_PAD * 2, 17,
            size=12, color=NSColor.secondaryLabelColor(),
        )
        self.addSubview_(self._snippet)

        # ── Open-in-Notes icon button (↗) — far right, vertically centred
        btn_y = int((ROW_H - OPEN_BTN_W) / 2)
        self._open_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(OPEN_BTN_X, btn_y, OPEN_BTN_W, OPEN_BTN_W)
        )
        sf_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "arrow.up.right.square", "Open in Notes"
        )
        if sf_img:
            self._open_btn.setImage_(sf_img)
        self._open_btn.setBezelStyle_(0)          # borderless
        self._open_btn.setBordered_(False)
        self._open_btn.setContentTintColor_(_accent())
        self._open_btn.setTarget_(self)
        self._open_btn.setAction_("openInNotesFromButton_")
        self.addSubview_(self._open_btn)

        return self

    def setResult_(self, result: dict) -> None:
        self._result = result
        self._title.setStringValue_(result.get("title", ""))
        self._folder.setFolder_(result.get("folder", ""))
        self._snippet.setStringValue_(result.get("snippet", ""))

    @objc.IBAction
    def openInNotesFromButton_(self, sender) -> None:
        if self._result and self._open_callback:
            self._open_callback(self._result)


# ---------------------------------------------------------------------------
# Main search panel
# ---------------------------------------------------------------------------

class SearchPanel:

    def __init__(self, searcher, prefs) -> None:
        self._searcher = searcher
        self._prefs    = prefs

        self._panel:            _KeyablePanel     | None = None
        self._query_field:      NSTextField        | None = None
        self._mode_control:     NSSegmentedControl | None = None
        self._table_view:       NSTableView        | None = None
        self._data_source:      _ResultsDataSource | None = None
        self._count_label:      NSTextField        | None = None
        self._delegate:         _QueryDelegate     | None = None
        self._answer_view:      NSTextView         | None = None
        self._answer_delegate:  _AnswerDelegate    | None = None

        self._current_mode:   str                  = prefs.default_mode
        self._debounce_timer: threading.Timer | None = None
        self._syn_id:         int = 0              # generation counter for synthesis cancellation

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

        FIELD_L = 44
        MODE_W  = 175
        FIELD_R = W - MODE_W - 12

        self._query_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_L, H - SEARCH_H + 13, FIELD_R - FIELD_L, 30)
        )
        self._query_field.setPlaceholderString_(random.choice(_PLACEHOLDERS))
        self._query_field.setFont_(NSFont.systemFontOfSize_(16))
        self._query_field.setBezeled_(False)
        self._query_field.setDrawsBackground_(False)
        self._query_field.setEditable_(True)
        self._query_field.setFocusRingType_(1)  # none

        self._delegate = _QueryDelegate.alloc().init()
        self._delegate.on_change      = self._on_query_changed
        self._delegate.on_escape      = self.hide
        self._delegate.on_enter_first = self._open_first_result
        self._query_field.setDelegate_(self._delegate)
        content.addSubview_(self._query_field)

        self._mode_control = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(W - MODE_W - 10, H - SEARCH_H + 15, MODE_W, 26)
        )
        self._mode_control.setSegmentCount_(3)
        for i, lbl in enumerate(_MODE_LABELS):
            self._mode_control.setLabel_forSegment_(lbl, i)
        self._mode_control.setSegmentStyle_(NSSegmentStyleCapsule)
        self._mode_control.setSelectedSegment_(_MODE_KEYS.index(self._current_mode))
        self._mode_control.setTarget_(self)
        self._mode_control.setAction_("modeChanged:")
        self._mode_control.setFont_(NSFont.systemFontOfSize_(11))
        content.addSubview_(self._mode_control)

        # Count / status label (bottom of search bar)
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

        # ── Separator 1: below search bar ────────────────────────────
        sep1 = NSBox.alloc().initWithFrame_(
            NSMakeRect(0, H - SEARCH_H, W, SEP_H)
        )
        sep1.setBoxType_(2)   # NSBoxSeparator
        content.addSubview_(sep1)

        # ── Answer / synthesis area ──────────────────────────────────
        # y position: just below sep1 going down (i.e. H - SEARCH_H - SEP_H - ANSWER_H)
        answer_y = H - SEARCH_H - SEP_H - ANSWER_H

        answer_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, answer_y, W, ANSWER_H)
        )
        answer_scroll.setHasVerticalScroller_(True)
        answer_scroll.setAutohidesScrollers_(True)
        answer_scroll.setDrawsBackground_(False)

        self._answer_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, ANSWER_H)
        )
        self._answer_view.setEditable_(False)
        self._answer_view.setSelectable_(True)
        self._answer_view.setDrawsBackground_(False)
        self._answer_view.setFont_(NSFont.systemFontOfSize_(13))
        self._answer_view.setTextColor_(NSColor.labelColor())
        self._answer_view.textContainer().setLineFragmentPadding_(0)
        from AppKit import NSMakeSize
        self._answer_view.setTextContainerInset_(NSMakeSize(16, 10))

        self._answer_delegate = _AnswerDelegate.alloc().init()
        self._answer_delegate._on_link_click = self._open_note_by_title
        self._answer_view.setDelegate_(self._answer_delegate)

        answer_scroll.setDocumentView_(self._answer_view)
        content.addSubview_(answer_scroll)

        # ── Separator 2: between answer area and results ─────────────
        sep2_y = answer_y - SEP2_H
        sep2 = NSBox.alloc().initWithFrame_(
            NSMakeRect(0, sep2_y, W, SEP2_H)
        )
        sep2.setBoxType_(2)
        content.addSubview_(sep2)

        # ── Results table ────────────────────────────────────────────
        table_h = sep2_y   # fill from 0 up to sep2

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
        # Rotate placeholder hint each time the panel opens
        self._query_field.cell().setPlaceholderString_(random.choice(_PLACEHOLDERS))
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
            # Cancel any in-flight synthesis and blank the answer area
            self._syn_id += 1
            self._set_answer("")
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
        _results   = results  # capture for closure

        def on_main():
            self._count_label.setStringValue_(count_text)
            self._set_results(_results)
            self._kick_synthesis(query, _results)

        call_on_main(on_main)

    def _set_results(self, results: list[dict]) -> None:
        self._data_source.set_results(results)
        self._table_view.reloadData()

    # ------------------------------------------------------------------
    # Synthesis (second-brain answer)
    # ------------------------------------------------------------------

    def _kick_synthesis(self, query: str, results: list[dict]) -> None:
        """Must be called on the main thread. Kicks off streaming synthesis."""
        from synthesizer import synthesize_stream

        self._syn_id += 1
        gen = self._syn_id

        if not results:
            self._set_answer("No notes found for this query.", secondary=True)
            return

        self._set_answer("✦  Thinking…", secondary=True)

        def on_chunk(text: str) -> None:
            if gen != self._syn_id:
                return
            self._set_answer(text)

        def on_done(text: str) -> None:
            if gen != self._syn_id:
                return
            self._set_answer(text)

        def on_error(err: str) -> None:
            if gen != self._syn_id:
                return
            self._set_answer("")   # fail silently — results are still shown

        synthesize_stream(query, results, on_chunk, on_done, on_error)

    def _set_answer(self, text: str, secondary: bool = False) -> None:
        """Update the synthesis text view (must be called on main thread)."""
        if self._answer_view is None:
            return
        if not text:
            self._answer_view.setString_("")
            return
        attr_str = _make_answer_attr_string(text, secondary=secondary)
        self._answer_view.textStorage().setAttributedString_(attr_str)

    def _open_note_by_title(self, title: str) -> None:
        """Open a note by title — used when user clicks a [[link]] in the synthesis."""
        for result in self._data_source.results():
            if result["title"] == title:
                self._open_note(result)
                return

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
