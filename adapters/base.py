"""
Base adapter protocol for Writers Room sources.

Every source (Apple Notes, Obsidian, Bear, etc.) implements this interface.
The indexer iterates adapters instead of folders, and the rest of the pipeline
is source-agnostic.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol, runtime_checkable


# Canonical date format — matches Apple Notes' AppleScript output.
# All adapters must emit dates in this format so searcher._note_date() works.
_DATE_FMT = "%A, %d %B %Y at %H:%M:%S"


def format_date(dt: datetime) -> str:
    """Format a datetime into the canonical Writers Room date string."""
    return dt.strftime(_DATE_FMT)


def strip_markdown(text: str) -> str:
    """
    Light markdown → plaintext. Removes headings, bold/italic markers,
    links, images, blockquotes, and horizontal rules. Preserves content.
    """
    # Remove images ![alt](url)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # Convert links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove heading markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}|_{1,3}', '', text)
    # Remove strikethrough
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # Remove blockquote markers
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Remove inline code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Remove code fences
    text = re.sub(r'^```.*?```', '', text, flags=re.MULTILINE | re.DOTALL)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


@runtime_checkable
class SourceAdapter(Protocol):
    """Protocol that all Writers Room source adapters implement."""

    @property
    def source_id(self) -> str:
        """Stable machine identifier: 'apple_notes', 'obsidian_MyVault', 'bear'."""
        ...

    @property
    def display_name(self) -> str:
        """Human label for UI: 'Apple Notes', 'Obsidian — MyVault', 'Bear'."""
        ...

    def is_available(self) -> bool:
        """Return True if this source is accessible on this machine."""
        ...

    def get_groups(self) -> list[str]:
        """Return list of group names (folders, tags, etc.)."""
        ...

    def read_group(self, group_name: str) -> list[dict]:
        """
        Read all notes in one group. Returns list of note dicts:
          id, folder, title, modified, created, content, source, open_url

        Returns empty list on error (never raises).
        """
        ...
