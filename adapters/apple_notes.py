"""
Apple Notes adapter — wraps the existing notes_reader.py.

Thin shim that adds `source` and `open_url` to each note dict
and namespaces the ID to avoid collisions with other sources.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from notes_reader import read_notes, get_folder_names


class AppleNotesAdapter:
    """Reads notes from the macOS Apple Notes app via AppleScript."""

    @property
    def source_id(self) -> str:
        return "apple_notes"

    @property
    def display_name(self) -> str:
        return "Apple Notes"

    def is_available(self) -> bool:
        """Available if we're on macOS (osascript exists)."""
        import shutil
        return shutil.which("osascript") is not None

    def get_groups(self) -> list[str]:
        try:
            return get_folder_names()
        except Exception:
            return []

    def read_group(self, group_name: str) -> list[dict]:
        try:
            notes = read_notes(folders=[group_name])
        except Exception:
            return []

        # Annotate each note with source metadata
        for note in notes:
            note["source"] = self.source_id
            note["open_url"] = f"applenotes://open/{note['folder']}/{note['title']}"

        return notes


if __name__ == "__main__":
    adapter = AppleNotesAdapter()
    print(f"Available: {adapter.is_available()}")
    groups = adapter.get_groups()
    print(f"Groups: {len(groups)}")
    if groups:
        notes = adapter.read_group(groups[0])
        print(f"First group '{groups[0]}': {len(notes)} notes")
        for n in notes[:3]:
            print(f"  [{n['source']}] {n['title']} — {n['folder']}")
