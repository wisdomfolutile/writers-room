"""
Source configuration for Writers Room.

Loads ~/.config/writers-room/sources.json and returns adapter instances.
When no config exists, defaults to Apple Notes only (backward compatible).
"""

from __future__ import annotations

import json
from pathlib import Path

from adapters.apple_notes import AppleNotesAdapter
from adapters.obsidian import ObsidianAdapter, discover_vaults
from adapters.bear import BearAdapter
from adapters.markdown_folder import MarkdownFolderAdapter

CONFIG_DIR = Path.home() / ".config" / "writers-room"
CONFIG_FILE = CONFIG_DIR / "sources.json"


def _default_config() -> dict:
    """Default: Apple Notes enabled, auto-discover Obsidian vaults and Bear."""
    sources = [{"type": "apple_notes", "enabled": True}]

    # Auto-discover Obsidian vaults
    for vault in discover_vaults():
        sources.append({
            "type": "obsidian",
            "vault_path": str(vault["path"]),
            "vault_name": vault["name"],
            "enabled": True,
        })

    # Auto-discover Bear
    bear = BearAdapter()
    if bear.is_available():
        sources.append({"type": "bear", "enabled": True})

    return {"sources": sources}


def load_config() -> dict:
    """Load source config from disk, or return defaults."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_config()


def save_config(config: dict) -> None:
    """Save source config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_active_adapters() -> list:
    """
    Return instantiated adapter objects for all enabled, available sources.
    Each adapter satisfies the SourceAdapter protocol.
    """
    config = load_config()
    adapters = []

    for src in config.get("sources", []):
        if not src.get("enabled", True):
            continue

        adapter = _make_adapter(src)
        if adapter and adapter.is_available():
            adapters.append(adapter)

    # Always have at least Apple Notes
    if not adapters:
        an = AppleNotesAdapter()
        if an.is_available():
            adapters.append(an)

    return adapters


def _make_adapter(src: dict):
    """Instantiate an adapter from a config entry."""
    t = src.get("type")

    if t == "apple_notes":
        return AppleNotesAdapter()

    elif t == "obsidian":
        vault_path = src.get("vault_path")
        vault_name = src.get("vault_name", Path(vault_path).name if vault_path else "Vault")
        if vault_path:
            return ObsidianAdapter(vault_name, vault_path)

    elif t == "bear":
        return BearAdapter()

    elif t == "markdown_folder":
        path = src.get("path")
        name = src.get("name", "Markdown")
        if path:
            return MarkdownFolderAdapter(path, name)

    return None


def list_sources() -> None:
    """Print all configured sources and their status."""
    config = load_config()
    print(f"\n{'Source':<35} {'Status':>10}")
    print("-" * 47)
    for src in config.get("sources", []):
        adapter = _make_adapter(src)
        enabled = src.get("enabled", True)
        if adapter:
            available = adapter.is_available()
            name = adapter.display_name
            status = "active" if (enabled and available) else "disabled" if not enabled else "unavailable"
        else:
            name = src.get("type", "unknown")
            status = "invalid config"
        print(f"  {name:<33} {status:>10}")


if __name__ == "__main__":
    list_sources()
    print()
    adapters = get_active_adapters()
    print(f"Active adapters: {len(adapters)}")
    for a in adapters:
        groups = a.get_groups()
        print(f"  {a.display_name}: {len(groups)} groups")
