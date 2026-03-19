"""
Obsidian adapter — reads markdown files from Obsidian vaults.

Discovers vaults from Obsidian's global registry, reads .md files,
parses optional YAML frontmatter, and strips markdown to plaintext.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .base import format_date, strip_markdown


# Obsidian stores its vault registry here on macOS
_OBSIDIAN_CONFIG = Path.home() / "Library/Application Support/obsidian/obsidian.json"

# Frontmatter regex: YAML block between --- delimiters at file start
_FRONTMATTER_RE = re.compile(r'\A---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Extract YAML frontmatter from markdown text.
    Returns (frontmatter_dict, body_without_frontmatter).
    Uses simple key: value parsing to avoid a PyYAML dependency.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    body = text[m.end():]
    fm = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip().strip('"').strip("'")
            if value:
                fm[key] = value
    return fm, body


def discover_vaults() -> list[dict]:
    """
    Read Obsidian's vault registry and return list of
    {"name": str, "path": Path} for vaults that exist on disk.
    """
    if not _OBSIDIAN_CONFIG.exists():
        return []

    try:
        data = json.loads(_OBSIDIAN_CONFIG.read_text())
        vaults = data.get("vaults", {})
    except (json.JSONDecodeError, OSError):
        return []

    result = []
    for _vault_id, info in vaults.items():
        vault_path = Path(info.get("path", ""))
        if vault_path.is_dir():
            result.append({
                "name": vault_path.name,
                "path": vault_path,
            })
    return result


class ObsidianAdapter:
    """Reads notes from a single Obsidian vault."""

    def __init__(self, vault_name: str, vault_path: str | Path):
        self._vault_name = vault_name
        self._vault_path = Path(vault_path)

    @property
    def source_id(self) -> str:
        return f"obsidian_{self._vault_name}"

    @property
    def display_name(self) -> str:
        return f"Obsidian — {self._vault_name}"

    def is_available(self) -> bool:
        return self._vault_path.is_dir()

    def get_groups(self) -> list[str]:
        """Return subdirectory names as groups, plus root-level files as the vault name."""
        if not self.is_available():
            return []

        groups = set()
        for md in self._vault_path.rglob("*.md"):
            if ".obsidian" in md.parts:
                continue
            rel = md.relative_to(self._vault_path)
            if len(rel.parts) == 1:
                groups.add(self._vault_name)  # root-level file
            else:
                groups.add(rel.parts[0])  # top-level subfolder
        return sorted(groups)

    def read_group(self, group_name: str) -> list[dict]:
        if not self.is_available():
            return []

        notes = []
        try:
            for md in self._vault_path.rglob("*.md"):
                if ".obsidian" in md.parts:
                    continue

                # Determine which group this file belongs to
                rel = md.relative_to(self._vault_path)
                if len(rel.parts) == 1:
                    file_group = self._vault_name
                else:
                    file_group = rel.parts[0]

                if file_group != group_name:
                    continue

                # Skip iCloud-evicted stubs
                if md.stat().st_size == 0:
                    continue

                note = self._read_file(md, rel)
                if note:
                    notes.append(note)
        except Exception:
            pass

        return notes

    def _read_file(self, path: Path, rel_path: Path) -> dict | None:
        """Read a single .md file and return a note dict."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        fm, body = _parse_frontmatter(text)
        content = strip_markdown(body)

        if not content.strip():
            return None

        stat = path.stat()
        title = fm.get("title") or path.stem
        folder = rel_path.parts[0] if len(rel_path.parts) > 1 else self._vault_name

        # Dates: prefer frontmatter, fall back to filesystem
        created_dt = self._parse_fm_date(fm.get("created")) or datetime.fromtimestamp(stat.st_birthtime)
        modified_dt = self._parse_fm_date(fm.get("modified")) or datetime.fromtimestamp(stat.st_mtime)

        rel_str = str(rel_path)
        note_id = f"{self.source_id}||{folder}||{title}||{format_date(created_dt)}"
        open_url = f"obsidian://open?vault={quote(self._vault_name)}&file={quote(rel_str)}"

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

    @staticmethod
    def _parse_fm_date(value: str | None) -> datetime | None:
        """Try common frontmatter date formats."""
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None


if __name__ == "__main__":
    vaults = discover_vaults()
    print(f"Found {len(vaults)} Obsidian vault(s)")
    for v in vaults:
        adapter = ObsidianAdapter(v["name"], v["path"])
        print(f"\n  {adapter.display_name} — available: {adapter.is_available()}")
        groups = adapter.get_groups()
        print(f"  Groups ({len(groups)}): {groups[:10]}")
        if groups:
            notes = adapter.read_group(groups[0])
            print(f"  First group '{groups[0]}': {len(notes)} notes")
            for n in notes[:3]:
                print(f"    {n['title']} — {n['open_url'][:60]}")
