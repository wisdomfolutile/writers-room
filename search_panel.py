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
    NSEvent,
    NSFloatingWindowLevel,
    NSMakeSize,
    NSViewMinXMargin,
    NSViewWidthSizable,
    NSViewHeightSizable,
)
from Foundation import NSNotificationCenter, NSURL, NSIndexSet

# ---------------------------------------------------------------------------
# NSPanel subclass — borderless, accepts keyboard input
# ---------------------------------------------------------------------------

class _KeyablePanel(NSPanel):
    def canBecomeKeyWindow(self):
        return True
    def canBecomeMainWindow(self):
        return False


# ---------------------------------------------------------------------------
# Window resign-key observer — drives "hide on click away" mode
# ---------------------------------------------------------------------------

class _WindowObserver(NSObject):
    """Receives NSWindowDidResignKeyNotification; calls _callback if set."""

    def init(self):
        self = objc.super(_WindowObserver, self).init()
        if self is None:
            return None
        self._callback = None
        return self

    def handleResignKey_(self, notification) -> None:
        if self._callback:
            self._callback()


# ---------------------------------------------------------------------------
# Resize observer — fires NSWindowDidResizeNotification → relayout
# ---------------------------------------------------------------------------

class _ResizeObserver(NSObject):
    def init(self):
        self = objc.super(_ResizeObserver, self).init()
        if self is None:
            return None
        self._callback = None
        return self

    def handleResize_(self, notification) -> None:
        if self._callback:
            self._callback()


# ---------------------------------------------------------------------------
# Resize grip — bottom-right corner drag handle
# ---------------------------------------------------------------------------

class _ResizeGrip(NSView):
    """
    Draws a subtle 3-dot diagonal indicator and handles mouse-drag resize.
    Top-left corner of the panel stays fixed; bottom-right corner moves.
    """

    def init(self):
        self = objc.super(_ResizeGrip, self).init()
        if self is None:
            return None
        self._drag_origin   = None
        self._initial_frame = None
        return self

    def drawRect_(self, rect) -> None:
        NSColor.tertiaryLabelColor().set()
        b = self.bounds()
        # Inset from edges so dots sit comfortably inside the rounded panel corner
        PAD_R = 8   # right inset
        PAD_B = 8   # bottom inset
        for i in range(3):
            x = b.size.width  - PAD_R - 2.5 - i * 5
            y = PAD_B         + i * 5
            NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, 2.5, 2.5)).fill()

    def mouseDown_(self, event) -> None:
        self._drag_origin   = NSEvent.mouseLocation()
        self._initial_frame = self.window().frame()

    def mouseDragged_(self, event) -> None:
        if self._drag_origin is None:
            return
        loc  = NSEvent.mouseLocation()
        dx   = loc.x - self._drag_origin.x
        dy   = loc.y - self._drag_origin.y   # positive = moved up
        f    = self._initial_frame
        new_w = max(MIN_W, f.size.width  + dx)
        new_h = max(MIN_H, f.size.height - dy)   # dy < 0 when dragging down → taller
        new_y = f.origin.y + f.size.height - new_h  # keep top edge fixed
        self.window().setFrame_display_(
            NSMakeRect(f.origin.x, new_y, new_w, new_h), True
        )

    def mouseUp_(self, event) -> None:
        self._drag_origin   = None
        self._initial_frame = None


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
STATUS_H  = 18          # status strip (results count / searching…) below sep1
ANSWER_H  = 112         # synthesis text area (was 130; 18 moved to STATUS_H)
SEP2_H    = 1           # separator between synthesis and results
ROW_H     = 64.0        # result row height
CORNER_R  = 16.0        # panel corner radius

# Total height: search + sep + status + answer + sep + 5 rows + footer = 516 (unchanged)
PANEL_H = SEARCH_H + SEP_H + STATUS_H + ANSWER_H + SEP2_H + int(ROW_H * 5) + 8

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

INNER_PAD  = 16   # left/right inner padding
OPEN_BTN_W = 22   # ↗ icon button size (square)
CHIP_H     = 20   # folder chip height

MIN_W     = 480   # minimum panel width during resize
MIN_H     = 300   # minimum panel height during resize
GRIP_SIZE = 28    # bottom-right resize grip (larger for padding room)


# ---------------------------------------------------------------------------
# AppleScript string helper — handles embedded double quotes via & quote &
# ---------------------------------------------------------------------------

def _as_string_lit(s: str) -> str:
    """
    Return an AppleScript string literal that safely embeds s.
    AppleScript has no backslash escaping; embedded " must be built via & quote &.
    e.g. _as_string_lit('It "works"') → '"It " & quote & "works" & quote & ""'
    """
    parts = s.split('"')
    if len(parts) == 1:
        return f'"{s}"'
    return ' & quote & '.join(f'"{p}"' for p in parts)


# ---------------------------------------------------------------------------
# CP1252 display fixer — corrects mojibake in legacy note content
# ---------------------------------------------------------------------------

def _fix_cp1252(s: str) -> str:
    """
    Bytes 0x80–0x9F are Windows-1252 printable chars (curly quotes, bullet, em-dash…)
    but Unicode control chars. Notes content from older imports stores them as
    those literal codepoints. Map them to their intended characters for display.
    """
    if not s or not any(0x80 <= ord(c) <= 0x9F for c in s):
        return s  # fast path
    out = []
    for ch in s:
        cp = ord(ch)
        if 0x80 <= cp <= 0x9F:
            try:
                out.append(bytes([cp]).decode('cp1252'))
            except (UnicodeDecodeError, ValueError):
                out.append(ch)
        else:
            out.append(ch)
    return ''.join(out)


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
    A folder name rendered as an inline code chip — SF Mono on a subtle rounded-rect
    background. Width is set dynamically by _ResultCell._update_folder_chip() after
    measuring the text; this view just owns the drawing and label.
    """

    def initWithFrame_(self, frame):
        self = objc.super(_FolderChip, self).initWithFrame_(frame)
        if self is None:
            return None
        # Label fills the view bounds; padding is achieved by the frame itself
        self._label = NSTextField.alloc().initWithFrame_(self.bounds())
        self._label.setEditable_(False)
        self._label.setBordered_(False)
        self._label.setDrawsBackground_(False)
        self._label.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10, 0))
        self._label.setTextColor_(NSColor.secondaryLabelColor())
        self._label.setAlignment_(2)      # NSTextAlignmentCenter — text centered in label
        self._label.setLineBreakMode_(4)  # NSLineBreakByTruncatingMiddle
        self.addSubview_(self._label)
        return self

    def drawRect_(self, rect) -> None:
        NSColor.labelColor().colorWithAlphaComponent_(0.07).set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 4.0, 4.0
        ).fill()

    def setFolder_(self, name: str) -> None:
        self._label.setStringValue_(name)
        # Keep label filling the full chip frame so centering is correct
        self._label.setFrame_(self.bounds())


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

        # Note title as a code chip — neutral bg + SF Mono + orange text (clickable)
        note_title = m.group(1)
        url = NSURL.URLWithString_(f"writersroom://{quote(note_title)}")
        link_attrs: dict = {
            NSFontAttributeName: NSFont.monospacedSystemFontOfSize_weight_(12, 0.0),
            NSForegroundColorAttributeName: _accent(),
            NSBackgroundColorAttributeName: NSColor.labelColor().colorWithAlphaComponent_(0.08),
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
        self.on_move_down:   Callable[[], None]    | None = None
        self.on_move_up:     Callable[[], None]    | None = None
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
        if sel == "moveDown:":
            if self.on_move_down:
                self.on_move_down()
            return True
        if sel == "moveUp:":
            if self.on_move_up:
                self.on_move_up()
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
        # Set to True during programmatic keyboard-nav selection so that
        # tableViewSelectionDidChange_ highlights without opening the note.
        self.keyboard_navigating: bool = False
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
        if row < 0 or row >= len(self._results):
            return
        if self.keyboard_navigating:
            # Arrow-key navigation: just highlight, don't open
            tv.scrollRowToVisible_(row)
            return
        if _ResultCell._button_just_clicked:
            # The ↗ button already opened the note — just clear selection quietly.
            _ResultCell._button_just_clicked = False
            self.keyboard_navigating = True      # suppress recursive notification
            tv.deselectAll_(None)
            self.keyboard_navigating = False
            return
        if self.on_open:
            # Mouse click on the row itself: open and deselect
            result = self._results[row]
            self.keyboard_navigating = True      # suppress recursive notification
            tv.deselectAll_(None)
            self.keyboard_navigating = False
            self.on_open(result)


# ---------------------------------------------------------------------------
# Result cell — title + snippet (left) · folder · ↗ button (right)
# ---------------------------------------------------------------------------

_TITLE_FONT   = NSFont.systemFontOfSize_weight_(15, 0.4)   # medium weight
_CHIP_FONT    = NSFont.monospacedSystemFontOfSize_weight_(10, 0)


class _ResultCell(NSView):
    # Class-level flag: set True when the ↗ button fires, so the
    # table's selectionDidChange handler knows to skip the duplicate open.
    _button_just_clicked: bool = False

    def initWithFrame_(self, frame):
        self = objc.super(_ResultCell, self).initWithFrame_(frame)
        if self is None:
            return None

        self._open_callback: Callable[[dict], None] | None = None
        self._result: dict | None = None

        W = frame.size.width or PANEL_W

        # ── Title — left side; right boundary is updated in _update_folder_chip
        self._title = _label(
            "", INNER_PAD, ROW_H - 28, W - INNER_PAD * 2 - OPEN_BTN_W - 6 - 60, 19,
            size=15, bold=False,
        )
        self._title.setFont_(_TITLE_FONT)
        self._title.setAutoresizingMask_(NSViewWidthSizable)
        self.addSubview_(self._title)

        # ── Snippet — below title, stretches with cell width
        self._snippet = _label(
            "", INNER_PAD, 10, W - INNER_PAD * 2, 17,
            size=12, color=NSColor.secondaryLabelColor(),
        )
        self._snippet.setAutoresizingMask_(NSViewWidthSizable)
        self.addSubview_(self._snippet)

        # ── Folder chip — starts with a placeholder frame; resized in _update_folder_chip
        chip_y = int((ROW_H - CHIP_H) / 2)   # vertically centred in row
        self._folder = _make_folder_chip(W - INNER_PAD - OPEN_BTN_W - 6 - 60,
                                         chip_y, 60, CHIP_H)
        self._folder.setAutoresizingMask_(NSViewMinXMargin)
        self.addSubview_(self._folder)

        # ── Open-in-Notes icon button (↗) — far right, same vertical centre as chip
        btn_y = int((ROW_H - OPEN_BTN_W) / 2)   # centred in full row height
        open_x = W - INNER_PAD - OPEN_BTN_W
        self._open_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(open_x, btn_y, OPEN_BTN_W, OPEN_BTN_W)
        )
        sf_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "arrow.up.right.square", "Open in Notes"
        )
        if sf_img:
            self._open_btn.setImage_(sf_img)
        self._open_btn.setBezelStyle_(0)
        self._open_btn.setBordered_(False)
        self._open_btn.setContentTintColor_(_accent())
        self._open_btn.setTarget_(self)
        self._open_btn.setAction_("openInNotesFromButton_")
        self._open_btn.setAutoresizingMask_(NSViewMinXMargin)
        self.addSubview_(self._open_btn)

        return self

    # ------------------------------------------------------------------
    # Dynamic folder chip sizing — called every time setResult_ fires
    # ------------------------------------------------------------------

    def _update_folder_chip(self, folder_name: str) -> None:
        """
        Measure the folder name text, resize the chip to fit snugly, and
        update the title width so it never overlaps the chip.
        All positions are relative to the current cell width.
        """
        W_cell = self.frame().size.width or PANEL_W

        # Measure text width at the chip font size
        if folder_name:
            attr_str = NSAttributedString.alloc().initWithString_attributes_(
                folder_name, {NSFontAttributeName: _CHIP_FONT}
            )
            text_w = attr_str.size().width
        else:
            text_w = 0

        # Chip width: text + 12px horizontal padding (6px per side), clamped
        chip_w = max(38, min(150, int(text_w) + 12))
        chip_y = int((ROW_H - CHIP_H) / 2)

        # Open button: right-padded from the cell edge
        open_x  = W_cell - INNER_PAD - OPEN_BTN_W
        # Chip: immediately left of the open button with a 6px gap
        chip_x  = open_x - 6 - chip_w

        # Reposition chip and refresh its internal label frame for centering
        self._folder.setFrame_(NSMakeRect(chip_x, chip_y, chip_w, CHIP_H))
        self._folder._label.setFrame_(self._folder.bounds())
        self._folder.setNeedsDisplay_(True)

        # Also keep open button at the correct x (handles cell-width changes on reuse)
        btn_y = int((ROW_H - OPEN_BTN_W) / 2)
        self._open_btn.setFrame_(NSMakeRect(open_x, btn_y, OPEN_BTN_W, OPEN_BTN_W))

        # Title: from left pad to 8px left of chip
        title_w = max(80, chip_x - INNER_PAD - 8)
        self._title.setFrame_(NSMakeRect(INNER_PAD, ROW_H - 28, title_w, 19))

        # Snippet: full available width
        self._snippet.setFrame_(NSMakeRect(INNER_PAD, 10, W_cell - INNER_PAD * 2, 17))

    def setResult_(self, result: dict) -> None:
        self._result = result
        self._title.setStringValue_(_fix_cp1252(result.get("title", "")))
        self._folder.setFolder_(result.get("folder", ""))
        self._snippet.setStringValue_(_fix_cp1252(result.get("snippet", "")))
        self._update_folder_chip(result.get("folder", ""))

    @objc.IBAction
    def openInNotesFromButton_(self, sender) -> None:
        _ResultCell._button_just_clicked = True
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
        self._win_observer:   _WindowObserver  | None = None

        # Layout refs (set in _build, used in _layout / _on_resize)
        self._vev:             NSVisualEffectView | None = None
        self._search_icon:     NSImageView        | None = None
        self._sep1:            NSBox              | None = None
        self._answer_scroll:   NSScrollView       | None = None
        self._sep2:            NSBox              | None = None
        self._table_scroll:    NSScrollView       | None = None
        self._resize_grip:     _ResizeGrip        | None = None
        self._resize_observer: _ResizeObserver    | None = None

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
        self._panel.setMovableByWindowBackground_(True)      # drag any background area to move
        self._panel.setMinSize_(NSMakeSize(MIN_W, MIN_H))    # enforce minimum dimensions
        self._panel.center()

        # Register for resign-key notifications (drives "hide on click away" mode)
        self._win_observer = _WindowObserver.alloc().init()
        self._win_observer._callback = self._on_resign_key
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self._win_observer,
            "handleResignKey:",
            "NSWindowDidResignKeyNotification",
            self._panel,
        )

        # Register for resize notifications → relayout all subviews
        self._resize_observer = _ResizeObserver.alloc().init()
        self._resize_observer._callback = self._on_resize
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self._resize_observer,
            "handleResize:",
            "NSWindowDidResizeNotification",
            self._panel,
        )

        content = self._panel.contentView()

        # ── Frosted glass background ─────────────────────────────────
        self._vev = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        vev = self._vev   # local alias for readability below
        vev.setMaterial_(_MATERIAL)
        vev.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        vev.setState_(_VEV_STATE)
        vev.setWantsLayer_(True)
        vev.layer().setCornerRadius_(CORNER_R)
        vev.layer().setMasksToBounds_(True)
        vev.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        content.addSubview_(vev)

        # ── Search bar row ───────────────────────────────────────────
        # Icon centred in SEARCH_H — matches the formula used in _layout()
        _icon_sz = 20
        _icon_y  = H - SEARCH_H + (SEARCH_H - _icon_sz) // 2
        self._search_icon = NSImageView.alloc().initWithFrame_(
            NSMakeRect(14, _icon_y, _icon_sz, _icon_sz)
        )
        sf_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "magnifyingglass", "Search"
        )
        if sf_img:
            self._search_icon.setImage_(sf_img)
            self._search_icon.setContentTintColor_(NSColor.tertiaryLabelColor())
        content.addSubview_(self._search_icon)

        FIELD_L = 44
        MODE_W  = 175
        FIELD_R = W - MODE_W - 12

        _field_h = 30
        _field_y = H - SEARCH_H + (SEARCH_H - _field_h) // 2
        self._query_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_L, _field_y, FIELD_R - FIELD_L, _field_h)
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
        self._delegate.on_move_down   = self._select_next_result
        self._delegate.on_move_up     = self._select_prev_result
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

        # ── Separator 1: below search bar ────────────────────────────
        self._sep1 = NSBox.alloc().initWithFrame_(
            NSMakeRect(0, H - SEARCH_H, W, SEP_H)
        )
        self._sep1.setBoxType_(2)   # NSBoxSeparator
        content.addSubview_(self._sep1)

        # ── Status strip: "searching…" / "5 results" — between sep1 and synthesis ──
        # Sits just below the divider line with clean padding on both sides
        status_y = H - SEARCH_H - SEP_H - STATUS_H
        label_h  = 12
        label_y  = status_y + (STATUS_H - label_h) // 2   # vertically centred in strip
        self._count_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(INNER_PAD, label_y, W - INNER_PAD * 2, label_h)
        )
        self._count_label.setStringValue_("")
        self._count_label.setEditable_(False)
        self._count_label.setBordered_(False)
        self._count_label.setDrawsBackground_(False)
        self._count_label.setFont_(NSFont.systemFontOfSize_(10))
        self._count_label.setTextColor_(NSColor.tertiaryLabelColor())
        content.addSubview_(self._count_label)

        # ── Answer / synthesis area ──────────────────────────────────
        # y position: below search bar + sep1 + status strip
        answer_y = H - SEARCH_H - SEP_H - STATUS_H - ANSWER_H

        self._answer_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, answer_y, W, ANSWER_H)
        )
        answer_scroll = self._answer_scroll   # local alias
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
        self._answer_view.setTextContainerInset_(NSMakeSize(16, 10))

        self._answer_delegate = _AnswerDelegate.alloc().init()
        self._answer_delegate._on_link_click = self._open_note_by_title
        self._answer_view.setDelegate_(self._answer_delegate)

        answer_scroll.setDocumentView_(self._answer_view)
        content.addSubview_(answer_scroll)

        # ── Separator 2: between answer area and results ─────────────
        sep2_y = answer_y - SEP2_H
        self._sep2 = NSBox.alloc().initWithFrame_(
            NSMakeRect(0, sep2_y, W, SEP2_H)
        )
        self._sep2.setBoxType_(2)
        content.addSubview_(self._sep2)

        # ── Results table ────────────────────────────────────────────
        table_h = sep2_y   # fill from 0 up to sep2

        self._table_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, table_h)
        )
        scroll = self._table_scroll   # local alias
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

        # ── Resize grip — bottom-right corner ────────────────────────
        self._resize_grip = _ResizeGrip.alloc().init()
        self._resize_grip.setFrame_(NSMakeRect(W - GRIP_SIZE, 0, GRIP_SIZE, GRIP_SIZE))
        content.addSubview_(self._resize_grip)

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

    def _on_resign_key(self) -> None:
        """Called when the panel loses key status. Hides unless persist_window is on."""
        if not self._prefs.persist_window:
            self.hide()

    def _on_resize(self) -> None:
        """Called (main thread) whenever the panel is resized. Relayouts all subviews."""
        f = self._panel.frame()
        self._layout(f.size.width, f.size.height)

    def _layout(self, W: float, H: float) -> None:
        """Reposition/resize all panel subviews for new dimensions W × H."""
        MODE_W  = 175
        FIELD_L = 44
        FIELD_R = W - MODE_W - 12

        # Vertical stack (top → bottom):
        #   search bar (SEARCH_H) → sep1 (SEP_H) → status strip (STATUS_H)
        #   → answer (ANSWER_H) → sep2 (SEP2_H) → results table (rest)
        sep1_y   = H - SEARCH_H
        status_y = sep1_y - SEP_H - STATUS_H
        answer_y = status_y - ANSWER_H
        sep2_y   = answer_y - SEP2_H
        table_h  = sep2_y

        self._vev.setFrame_(NSMakeRect(0, 0, W, H))

        # Search bar elements — icon and query field vertically centred in SEARCH_H
        icon_size = 20
        icon_y    = H - SEARCH_H + (SEARCH_H - icon_size) // 2
        self._search_icon.setFrame_(NSMakeRect(14, icon_y, icon_size, icon_size))
        field_h = 30
        field_y = H - SEARCH_H + (SEARCH_H - field_h) // 2
        self._query_field.setFrame_(NSMakeRect(FIELD_L, field_y, FIELD_R - FIELD_L, field_h))
        self._mode_control.setFrame_(NSMakeRect(W - MODE_W - 10, H - SEARCH_H + 15, MODE_W, 26))

        # Sep1
        self._sep1.setFrame_(NSMakeRect(0, sep1_y, W, SEP_H))

        # Status label — vertically centred in STATUS strip
        label_h = 12
        label_y = status_y + (STATUS_H - label_h) // 2
        self._count_label.setFrame_(NSMakeRect(INNER_PAD, label_y, W - INNER_PAD * 2, label_h))

        # Answer / synthesis
        self._answer_scroll.setFrame_(NSMakeRect(0, answer_y, W, ANSWER_H))
        self._answer_view.setFrame_(NSMakeRect(0, 0, W, ANSWER_H))
        self._answer_view.textContainer().setContainerSize_(NSMakeSize(W - 32, 1e7))

        # Sep2
        self._sep2.setFrame_(NSMakeRect(0, sep2_y, W, SEP2_H))

        # Results table
        self._table_scroll.setFrame_(NSMakeRect(0, 0, W, table_h))
        self._table_view.setFrame_(NSMakeRect(0, 0, W, table_h))

        # Resize grip
        self._resize_grip.setFrame_(NSMakeRect(W - GRIP_SIZE, 0, GRIP_SIZE, GRIP_SIZE))

        # Widen the table column so cells get the new width
        cols = self._table_view.tableColumns()
        if cols:
            cols[0].setWidth_(W)

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
            label = "deep search…" if self._prefs.use_hyde else "searching…"
            call_on_main(lambda: self._count_label.setStringValue_(label))

    def _set_mode(self, mode: str) -> None:
        if mode in _MODE_KEYS:
            self._current_mode = mode
            idx = _MODE_KEYS.index(mode)
            call_on_main(lambda: self._mode_control.setSelectedSegment_(idx))

    # ------------------------------------------------------------------
    # Search (background thread)
    # ------------------------------------------------------------------

    def _run_search_bg(self, query: str) -> None:
        n        = self._prefs.n_results
        mode     = self._current_mode
        use_hyde = self._prefs.use_hyde and mode != "keyword"
        try:
            results = self._searcher.search(query, n=n, mode=mode, use_hyde=use_hyde)
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
        self._table_view.deselectAll_(None)   # clear any keyboard-nav highlight

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
        """Open a note by title — used when user clicks a [[link]] in the synthesis.
        The AI may not reproduce the exact title, so we fall back to fuzzy matching.
        If nothing in the current results matches, try AppleScript by title alone.
        """
        results = self._data_source.results()
        t = title.strip().lower()
        # 1. Exact match
        for r in results:
            if r["title"] == title:
                self._open_note(r)
                return
        # 2. Case-insensitive exact
        for r in results:
            if r["title"].strip().lower() == t:
                self._open_note(r)
                return
        # 3. Partial — AI may have abbreviated or paraphrased the title
        for r in results:
            rt = r["title"].strip().lower()
            if t in rt or rt in t:
                self._open_note(r)
                return
        # 4. Fallback — search across all accounts by title alone
        self._open_note_by_title_direct(title)

    def _open_note_by_title_direct(self, title: str) -> None:
        """Last resort: ask Notes to show the first note matching this title."""
        title_as = _as_string_lit(title)
        script = (
            f'tell application "Notes"\n'
            f'  repeat with acct in every account\n'
            f'    try\n'
            f'      show (first note of acct whose name is {title_as})\n'
            f'      return\n'
            f'    end try\n'
            f'  end repeat\n'
            f'end tell'
        )
        subprocess.Popen(["osascript", "-e", script])

    # ------------------------------------------------------------------
    # Open note
    # ------------------------------------------------------------------

    def _open_first_result(self) -> None:
        """Enter key: open the keyboard-highlighted row, or the first result."""
        results = self._data_source.results()
        if not results:
            return
        row = self._table_view.selectedRow()
        if 0 <= row < len(results):
            self._open_note(results[row])
        else:
            self._open_note(results[0])

    # ------------------------------------------------------------------
    # Keyboard navigation — ↓ / ↑ cycle through result rows
    # ------------------------------------------------------------------

    def _select_row(self, row: int) -> None:
        """Highlight row at index without opening the note."""
        self._data_source.keyboard_navigating = True
        self._table_view.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(row), False
        )
        self._data_source.keyboard_navigating = False
        self._table_view.scrollRowToVisible_(row)

    def _select_next_result(self) -> None:
        n = len(self._data_source.results())
        if n == 0:
            return
        row = self._table_view.selectedRow()
        next_row = (row + 1) if 0 <= row < n - 1 else 0
        self._select_row(next_row)

    def _select_prev_result(self) -> None:
        n = len(self._data_source.results())
        if n == 0:
            return
        row = self._table_view.selectedRow()
        prev_row = (row - 1) if row > 0 else n - 1
        self._select_row(prev_row)

    def _open_note(self, result: dict) -> None:
        title_as  = _as_string_lit(result["title"])
        folder_as = _as_string_lit(result["folder"])
        # Iterate all accounts — a bare `folder "X"` fails for non-default accounts
        script = (
            f'tell application "Notes"\n'
            f'  repeat with acct in every account\n'
            f'    try\n'
            f'      show (first note of folder {folder_as} of acct whose name is {title_as})\n'
            f'      return\n'
            f'    end try\n'
            f'  end repeat\n'
            f'end tell'
        )
        subprocess.Popen(["osascript", "-e", script])
