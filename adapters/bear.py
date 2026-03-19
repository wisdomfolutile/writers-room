"""
Bear adapter — reads notes from Bear's SQLite database.

Opens the database read-only (safe while Bear is running).
Maps Bear tags to Writers Room folders.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .base import format_date, strip_markdown


# Bear's database location on macOS
_BEAR_DB = Path.home() / "Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite"

# Core Data epoch: 2001-01-01 00:00:00 UTC
_COREDATA_EPOCH = 978307200

# Bear inline tags: #tag or #tag/subtag (must not be preceded by non-whitespace)
_BEAR_TAG_RE = re.compile(r'(?<!\S)#[\w/.\-]+\s?')

# SQL to read notes with their tags
_NOTES_SQL = """
SELECT
    n.ZUNIQUEIDENTIFIER AS note_uuid,
    n.ZTITLE            AS title,
    n.ZTEXT             AS body,
    n.ZCREATIONDATE     AS created_ts,
    n.ZMODIFICATIONDATE AS modified_ts,
    GROUP_CONCAT(t.ZTITLE, '||') AS tags
FROM ZSFNOTE n
LEFT OUTER JOIN Z_7TAGS jt ON n.Z_PK = jt.Z_7NOTES
LEFT OUTER JOIN ZSFNOTETAG t ON jt.Z_14TAGS = t.Z_PK
WHERE n.ZTRASHED = 0
  AND (n.ZARCHIVED IS NULL OR n.ZARCHIVED = 0)
GROUP BY n.Z_PK
"""


def _coredata_to_datetime(ts: float) -> datetime:
    """Convert a Core Data timestamp to a Python datetime."""
    return datetime.fromtimestamp(ts + _COREDATA_EPOCH)


def _primary_tag(tags_str: str | None) -> str:
    """Pick the shallowest (shortest) tag as the folder. Falls back to 'Untagged'."""
    if not tags_str:
        return "Untagged"
    tags = [t.strip() for t in tags_str.split("||") if t.strip()]
    if not tags:
        return "Untagged"
    # Shortest tag = shallowest in hierarchy
    return min(tags, key=len)


class BearAdapter:
    """Reads notes from the Bear app's SQLite database."""

    @property
    def source_id(self) -> str:
        return "bear"

    @property
    def display_name(self) -> str:
        return "Bear"

    def is_available(self) -> bool:
        return _BEAR_DB.exists()

    def get_groups(self) -> list[str]:
        if not self.is_available():
            return []
        try:
            conn = sqlite3.connect(f"file:///{_BEAR_DB}?mode=ro", uri=True)
            cursor = conn.execute("SELECT DISTINCT ZTITLE FROM ZSFNOTETAG ORDER BY ZTITLE")
            tags = [row[0] for row in cursor if row[0]]
            conn.close()
            return tags + ["Untagged"]
        except Exception:
            return []

    def read_group(self, group_name: str) -> list[dict]:
        if not self.is_available():
            return []

        try:
            conn = sqlite3.connect(f"file:///{_BEAR_DB}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(_NOTES_SQL).fetchall()
            conn.close()
        except Exception:
            return []

        notes = []
        for row in rows:
            tag = _primary_tag(row["tags"])
            if tag != group_name:
                continue

            note = self._row_to_note(row, tag)
            if note:
                notes.append(note)

        return notes

    def _row_to_note(self, row: sqlite3.Row, folder: str) -> dict | None:
        """Convert a database row to a note dict."""
        body = row["body"] or ""
        uuid = row["note_uuid"] or ""
        title = row["title"] or ""

        if not body.strip():
            return None

        # Strip Bear's inline tags and markdown
        content = _BEAR_TAG_RE.sub('', body)
        content = strip_markdown(content)

        if not content.strip():
            return None

        created_dt = _coredata_to_datetime(row["created_ts"])
        modified_dt = _coredata_to_datetime(row["modified_ts"])

        return {
            "id": f"bear||{folder}||{uuid}",
            "folder": folder,
            "title": title,
            "modified": format_date(modified_dt),
            "created": format_date(created_dt),
            "content": content,
            "source": self.source_id,
            "open_url": f"bear://x-callback-url/open-note?id={quote(uuid)}",
        }


if __name__ == "__main__":
    adapter = BearAdapter()
    print(f"Available: {adapter.is_available()}")
    groups = adapter.get_groups()
    print(f"Groups ({len(groups)}): {groups[:10]}")
    if groups:
        notes = adapter.read_group(groups[0])
        print(f"First group '{groups[0]}': {len(notes)} notes")
        for n in notes[:3]:
            print(f"  {n['title']} — {n['open_url'][:60]}")
