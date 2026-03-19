"""
Reads notes from Apple Notes via AppleScript.

Uses batch property access per folder (one AppleEvent per folder, not per note)
and writes to a temp file to avoid O(n²) string concatenation in AppleScript.
For large folders, reads in chunks to avoid AppleEvent memory/timeout limits.
"""

import subprocess
import tempfile
import os
from pathlib import Path
from bs4 import BeautifulSoup

FIELD_SEP = "~~WRROOM~~"
NOTE_END = "~~NOTEEND~~"

# Max notes per AppleScript call — keeps memory and time per call manageable
APPLESCRIPT_CHUNK_SIZE = 200


def _make_count_script(folder_name: str, account_name: str) -> str:
    """AppleScript to count notes in a folder, accessed via account."""
    ef = folder_name.replace('"', '\\"')
    ea = account_name.replace('"', '\\"')
    return f"""
with timeout of 120 seconds
    tell application "Notes"
        try
            return count of notes of folder "{ef}" of account "{ea}"
        on error
            return 0
        end try
    end tell
end timeout
"""


def _make_chunk_script(output_path: str, folder_name: str, account_name: str, start_idx: int, end_idx: int) -> str:
    """
    AppleScript that reads notes start_idx through end_idx (1-based, inclusive)
    from a named folder, appending delimited records to output_path.
    Uses native range specifier (notes X through Y) which supports batch
    property access, unlike list slicing.
    """
    ef = folder_name.replace('"', '\\"')
    ea = account_name.replace('"', '\\"')
    return f"""
set outputPath to "{output_path}"
set sep to "{FIELD_SEP}"
set noteEnd to "{NOTE_END}"

set fileRef to open for access POSIX file outputPath with write permission

with timeout of 120 seconds
    tell application "Notes"
        try
            set targetFolder to folder "{ef}" of account "{ea}"
        on error
            close access fileRef
            return
        end try

        set noteTitles to name of (notes {start_idx} through {end_idx} of targetFolder)
        set noteMods to modification date of (notes {start_idx} through {end_idx} of targetFolder)
        set noteCreates to creation date of (notes {start_idx} through {end_idx} of targetFolder)
        set noteBodies to body of (notes {start_idx} through {end_idx} of targetFolder)
        set batchCount to count of noteTitles

        repeat with i from 1 to batchCount
            try
                set rec to "{ef}" & sep & (item i of noteTitles as string) & sep & ((item i of noteMods) as string) & sep & ((item i of noteCreates) as string) & sep & (item i of noteBodies as string) & noteEnd
                write rec to fileRef starting at eof as «class utf8»
            end try
        end repeat
    end tell
end timeout

close access fileRef
"""


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
                    try
                        set rec to folderName & sep & (item i of noteTitles as string) & sep & ((item i of noteMods) as string) & sep & ((item i of noteCreates) as string) & sep & (item i of noteBodies as string) & noteEnd
                        write rec to fileRef as «class utf8»
                    end try
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


def _get_folder_note_count(folder_name: str, account_name: str) -> int:
    """Return the number of unprotected notes in a folder, or -1 on error."""
    result = subprocess.run(
        ["osascript", "-e", _make_count_script(folder_name, account_name)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def _retry_subchunks(
    tmp_path: str, folder_name: str, account_name: str,
    start: int, end: int, depth: int,
) -> None:
    """
    When a chunk fails (usually encoding errors in one note crashing the batch
    property access), split it in half and retry each half. Recurse until we
    isolate the bad note(s) or hit single-note granularity.
    """
    if start > end:
        return
    if depth > 8:  # safety limit — don't recurse forever
        return

    # At single-note granularity, just try it and move on if it fails
    if start == end:
        script = _make_chunk_script(tmp_path, folder_name, account_name, start, end)
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            indent = "      " + "  " * depth
            print(f"{indent}note {start}: skipped (encoding error)")
        return

    mid = (start + end) // 2
    indent = "      " + "  " * depth

    # Try first half
    script = _make_chunk_script(tmp_path, folder_name, account_name, start, mid)
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode == 0:
        print(f"{indent}recovered notes {start}-{mid}")
    else:
        print(f"{indent}notes {start}-{mid} failed, splitting...")
        _retry_subchunks(tmp_path, folder_name, account_name, start, mid, depth + 1)

    # Try second half
    script = _make_chunk_script(tmp_path, folder_name, account_name, mid + 1, end)
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode == 0:
        print(f"{indent}recovered notes {mid + 1}-{end}")
    else:
        print(f"{indent}notes {mid + 1}-{end} failed, splitting...")
        _retry_subchunks(tmp_path, folder_name, account_name, mid + 1, end, depth + 1)


def _read_single_folder(folder_name: str, account_name: str) -> list[dict]:
    """
    Read notes from one folder. Returns empty list if the folder errors.
    For large folders, reads in chunks of APPLESCRIPT_CHUNK_SIZE to avoid
    AppleEvent memory/timeout limits.
    """
    note_count = _get_folder_note_count(folder_name, account_name)
    if note_count <= 0:
        # Fall back to the original single-shot script for small/unknown folders
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
                return []
            raw = Path(tmp_path).read_text(encoding="utf-8", errors="replace")
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        return _parse_raw(raw)

    # Chunked path for folders with known note count
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as tmp:
        tmp_path = tmp.name
    # Initialise the file (chunks will append)
    Path(tmp_path).write_text("", encoding="utf-8")

    total_chunks = -(-note_count // APPLESCRIPT_CHUNK_SIZE)  # ceiling division
    try:
        for chunk_num, start in enumerate(range(1, note_count + 1, APPLESCRIPT_CHUNK_SIZE), 1):
            end = min(start + APPLESCRIPT_CHUNK_SIZE - 1, note_count)
            print(f"    chunk {chunk_num}/{total_chunks} (notes {start}-{end})...", end=" ", flush=True)
            script = _make_chunk_script(tmp_path, folder_name, account_name, start, end)
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                print("ok")
                continue

            # Chunk failed — retry with smaller sub-chunks to salvage what we can.
            # Binary-style split: try halves, then quarters, etc.
            err = result.stderr.strip()[:120] if result.stderr else "unknown error"
            print(f"FAILED ({err})")
            _retry_subchunks(tmp_path, folder_name, account_name, start, end, depth=0)

        raw = Path(tmp_path).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass

    return _parse_raw(raw)


def _parse_raw(raw: str) -> list[dict]:
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
    folder_account_map = get_folder_account_map()
    target_folders = folders if folders is not None else list(folder_account_map.keys())

    all_notes = []
    skipped = []

    for i, folder_name in enumerate(target_folders, 1):
        if verbose:
            print(f"  [{i}/{len(target_folders)}] {folder_name}...", end=" ", flush=True)

        account_name = folder_account_map.get(folder_name, "iCloud")
        notes = _read_single_folder(folder_name, account_name)

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


def get_folder_account_map() -> dict[str, str]:
    """
    Return a mapping of {folder_name: account_name} for all folders.
    Uses batch property access per account (fast), then combines in Python.
    """
    # Step 1: get account names
    acct_result = subprocess.run(
        ["osascript", "-e", 'tell application "Notes" to return name of every account'],
        capture_output=True, text=True, timeout=30,
    )
    if acct_result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {acct_result.stderr.strip()}")
    account_names = [a.strip() for a in acct_result.stdout.strip().split(",") if a.strip()]

    mapping: dict[str, str] = {}
    for acct_name in account_names:
        escaped = acct_name.replace('"', '\\"')
        folder_result = subprocess.run(
            ["osascript", "-e",
             f'tell application "Notes" to return name of every folder of account "{escaped}"'],
            capture_output=True, text=True, timeout=30,
        )
        if folder_result.returncode != 0:
            continue
        for fname in folder_result.stdout.strip().split(","):
            fname = fname.strip()
            if fname:
                mapping[fname] = acct_name
    return mapping


def get_folder_names() -> list[str]:
    """Get all folder names quickly, without reading notes."""
    return list(get_folder_account_map().keys())


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
