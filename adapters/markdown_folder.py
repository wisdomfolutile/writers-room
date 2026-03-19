"""
Generic markdown folder adapter — reads .md files from any directory.

Works with iA Writer, Typora, or any app that stores notes as markdown
files in a folder. Subfolders become groups.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .base import format_date, strip_markdown


class MarkdownFolderAdapter:
    """Reads .md files from a user-specified directory."""

    def __init__(self, root_path: str | Path, name: str = "Markdown"):
        self._root = Path(root_path)
        self._name = name

    @property
    def source_id(self) -> str:
        # Sanitize name for use as ID
        safe = self._name.replace(" ", "_").lower()
        return f"markdown_{safe}"

    @property
    def display_name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._root.is_dir()

    def get_groups(self) -> list[str]:
        if not self.is_available():
            return []

        groups = set()
        for md in self._root.rglob("*.md"):
            rel = md.relative_to(self._root)
            if len(rel.parts) == 1:
                groups.add(self._name)  # root-level
            else:
                groups.add(rel.parts[0])
        return sorted(groups)

    def read_group(self, group_name: str) -> list[dict]:
        if not self.is_available():
            return []

        notes = []
        try:
            for md in self._root.rglob("*.md"):
                rel = md.relative_to(self._root)
                file_group = self._name if len(rel.parts) == 1 else rel.parts[0]

                if file_group != group_name:
                    continue

                if md.stat().st_size == 0:
                    continue

                note = self._read_file(md, rel)
                if note:
                    notes.append(note)
        except Exception:
            pass

        return notes

    def _read_file(self, path: Path, rel_path: Path) -> dict | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        content = strip_markdown(text)
        if not content.strip():
            return None

        stat = path.stat()
        title = path.stem
        folder = rel_path.parts[0] if len(rel_path.parts) > 1 else self._name

        created_dt = datetime.fromtimestamp(stat.st_birthtime)
        modified_dt = datetime.fromtimestamp(stat.st_mtime)

        note_id = f"{self.source_id}||{folder}||{title}||{format_date(created_dt)}"
        open_url = f"file:///{quote(str(path.resolve()))}"

        return {
            "id": note_id,
            "folder": folder,
            "title": title,
            "modified": format_date(modified_dt),
            "created": format_date(created_dt),
            "content": content,
            "source": self.source_id,
            "open_url": open_url,
        }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    adapter = MarkdownFolderAdapter(path, name="Test")
    print(f"Available: {adapter.is_available()}")
    groups = adapter.get_groups()
    print(f"Groups ({len(groups)}): {groups[:10]}")
    if groups:
        notes = adapter.read_group(groups[0])
        print(f"First group '{groups[0]}': {len(notes)} notes")
        for n in notes[:3]:
            print(f"  {n['title']}")
