"""
Reads notes from Apple Notes via AppleScript.

Uses batch property access per folder (one AppleEvent per folder, not per note)
and writes to a temp file to avoid O(n²) string concatenation in AppleScript.
"""

import subprocess
import tempfile
import os
from pathlib import Path
from bs4 import BeautifulSoup

FIELD_SEP = "~~WRROOM~~"
NOTE_END = "~~NOTEEND~~"


def _make_reader_script(output_path: str, folders: list[str] | None = None) -> str:
    """
    AppleScript that reads notes folder-by-folder using batch property access.
    Writes each note as a delimited record to a temp file.
    Optionally filters to specific folder names.

    Note: `id` doesn't support batch access in Notes' AppleScript dictionary,
    so we build a stable synthetic ID from folder + title + creation date in Python.
    """
    if folders:
        folder_filter = "{" + ", ".join(f'"{f}"' for f in folders) + "}"
        folder_condition = "if folderNames contains folderName then"
        folder_setup = f"    set folderNames to {folder_filter}\n"
    else:
        folder_condition = "if true then"
        folder_setup = ""

    return f"""
set outputPath to "{output_path}"
set sep to "{FIELD_SEP}"
set noteEnd to "{NOTE_END}"

set fileRef to open for access POSIX file outputPath with write permission
set eof of fileRef to 0

tell application "Notes"
{folder_setup}    set allFolders to every folder
    repeat with aFolder in allFolders
        set folderName to name of aFolder
        {folder_condition}
            -- Use inline specifier each time so batch property access works
            -- (storing in a variable loses the live specifier, breaking batch access)
            set noteCount to count of (every note of aFolder whose password protected is false)
            if noteCount > 0 then
                set noteTitles to name of (every note of aFolder whose password protected is false)
                set noteMods to modification date of (every note of aFolder whose password protected is false)
                set noteCreates to creation date of (every note of aFolder whose password protected is false)
                set noteBodies to body of (every note of aFolder whose password protected is false)
                repeat with i from 1 to noteCount
                    set rec to folderName & sep & (item i of noteTitles as string) & sep & ((item i of noteMods) as string) & sep & ((item i of noteCreates) as string) & sep & (item i of noteBodies as string) & noteEnd
                    write rec to fileRef
                end repeat
            end if
        end if
    end repeat
end tell

close access fileRef
"""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def _read_single_folder(folder_name: str) -> list[dict]:
    """Read notes from one folder. Returns empty list if the folder errors."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as tmp:
        tmp_path = tmp.name

    try:
        script = _make_reader_script(tmp_path, folders=[folder_name])
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            return []  # silently skip this folder
        raw = Path(tmp_path).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass

    notes = []
    for record in raw.split(NOTE_END):
        record = record.strip()
        if not record:
            continue

        parts = record.split(FIELD_SEP, 4)
        if len(parts) < 5:
            continue

        folder, title, modified, created, body_html = parts
        folder = folder.strip()
        title = title.strip()
        modified = modified.strip()
        created = created.strip()

        note_id = f"{folder}||{title}||{created}"
        content = html_to_text(body_html)

        notes.append(
            {
                "id": note_id,
                "folder": folder,
                "title": title,
                "modified": modified,
                "created": created,
                "content": content,
            }
        )
    return notes


def read_notes(
    folders: list[str] | None = None,
    include_content: bool = True,
    verbose: bool = False,
) -> list[dict]:
    """
    Read notes from Apple Notes, one folder at a time.
    Folders that error (locked, auth-required, syncing) are skipped gracefully.

    Args:
        folders: If set, only read from these folders. None = all folders.
        verbose: Print per-folder progress.

    Returns:
        List of note dicts with: id, folder, title, modified, created, content
    """
    target_folders = folders if folders is not None else get_folder_names()

    all_notes = []
    skipped = []

    for i, folder_name in enumerate(target_folders, 1):
        if verbose:
            print(f"  [{i}/{len(target_folders)}] {folder_name}...", end=" ", flush=True)

        notes = _read_single_folder(folder_name)

        if verbose:
            if notes:
                print(f"{len(notes)} notes")
            else:
                print("skipped")

        if notes:
            all_notes.extend(notes)
        else:
            skipped.append(folder_name)

    if verbose and skipped:
        print(f"\n  Skipped {len(skipped)} folders: {', '.join(skipped)}")

    return all_notes


def read_all_notes(verbose: bool = False) -> list[dict]:
    return read_notes(verbose=verbose)


def get_folder_names() -> list[str]:
    """Get all folder names quickly, without reading notes."""
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Notes" to return name of every folder'],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {result.stderr.strip()}")
    raw = result.stdout.strip()
    return [f.strip() for f in raw.split(",") if f.strip()]


if __name__ == "__main__":
    import sys

    folders_arg = None
    if "--folder" in sys.argv:
        idx = sys.argv.index("--folder")
        folders_arg = [sys.argv[idx + 1]]

    print("Reading notes from Apple Notes...")
    if folders_arg:
        print(f"Filtering to folder: {folders_arg}")
        notes = read_notes(folders=folders_arg, verbose=True)
    else:
        # For smoke test, just read the first folder
        folder_names = get_folder_names()
        print(f"Found {len(folder_names)} folders. Reading first folder as smoke test...")
        notes = read_notes(folders=[folder_names[0]], verbose=True)

    print(f"\nRead {len(notes)} notes\n")
    for n in notes[:3]:
        print(f"[{n['folder']}] {n['title']}")
        print(f"  Modified: {n['modified']}")
        print(f"  Content preview: {n['content'][:120]!r}")
        print()
