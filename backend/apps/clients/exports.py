"""Turn a client's selection into files the studio uses with the originals on its own disk.

Paths are relative to the folder the studio chose in the uploader (the event folder).
The copy scripts copy every file sharing the selected photo's base name, so RAW+JPEG pairs
and .xmp sidecars come along, and keep the subfolders inside a new "Selected" folder.
"""

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone
from django.utils.text import slugify

FORMATS = {"csv", "txt", "lightroom", "script-mac", "script-windows"}


@dataclass
class Row:
    photo_id: str
    relative_path: str
    album: str
    note: str
    selected_at: datetime

    @property
    def folder(self) -> str:
        return self.relative_path.rsplit("/", 1)[0] if "/" in self.relative_path else ""

    @property
    def filename(self) -> str:
        return self.relative_path.rsplit("/", 1)[-1]

    @property
    def base_name(self) -> str:
        """Filename without its extension; never empty, so a copy pattern cannot match everything."""
        name = self.filename
        stem = name.rsplit(".", 1)[0] if "." in name else name
        return stem or name


@dataclass
class ExportFile:
    content: bytes
    filename: str
    content_type: str


def build(fmt: str, event_title: str, client_name: str, rows: list[Row]) -> ExportFile:
    stem = f"{slugify(event_title)[:60] or 'event'}-selection"
    if fmt == "csv":
        return ExportFile(_csv(rows), f"{stem}.csv", "text/csv; charset=utf-8")
    if fmt == "txt":
        text = "\n".join(r.relative_path for r in rows) + "\n"
        return ExportFile(text.encode(), f"{stem}.txt", "text/plain; charset=utf-8")
    if fmt == "lightroom":
        return ExportFile(
            _lightroom(rows).encode(), f"{stem}-lightroom.txt", "text/plain; charset=utf-8"
        )
    if fmt == "script-mac":
        return ExportFile(
            _mac_script(event_title, client_name, rows).encode(),
            "copy-selected.sh",
            "text/x-shellscript; charset=utf-8",
        )
    if fmt == "script-windows":
        script = _windows_script(event_title, client_name, rows).replace("\n", "\r\n")
        return ExportFile(script.encode(), "copy-selected.cmd", "application/octet-stream")
    raise ValueError(f"Unknown format {fmt}")


def _cell(value) -> str:
    """Stop spreadsheet formula injection: a note like =HYPERLINK(...) stays plain text."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv(rows: list[Row]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["number", "folder", "filename", "path", "album", "note", "selected_at", "photo_id"]
    )
    for i, r in enumerate(rows, 1):
        writer.writerow(
            [
                i,
                _cell(r.folder),
                _cell(r.filename),
                _cell(r.relative_path),
                _cell(r.album),
                _cell(r.note),
                timezone.localtime(r.selected_at).strftime("%Y-%m-%d %H:%M"),
                r.photo_id,
            ]
        )
    return ("﻿" + out.getvalue()).encode()  # BOM so Excel reads UTF-8 names correctly


def _lightroom(rows: list[Row]) -> str:
    """Paste into Lightroom Classic: Library Filter > Text > Filename > Contains."""
    names = list(dict.fromkeys(r.base_name for r in rows))
    return ", ".join(names) + "\n"


def _comment_text(value: str) -> str:
    """Event titles and client names in script comments: letters, digits and simple
    punctuation only, on one line, so they can never become a command."""
    kept = "".join(ch if ch.isalnum() or ch in " .,'-_" else " " for ch in value)
    return " ".join(kept.split())[:80] or "-"


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _mac_script(event_title: str, client_name: str, rows: list[Row]) -> str:
    lines = [
        "#!/bin/bash",
        f"# {len(rows)} photos selected by {_comment_text(client_name)} for {_comment_text(event_title)}.",
        "# Put this file in the event folder you uploaded, then in Terminal run:",
        "#   bash copy-selected.sh",
        '# Copies are made in a new "Selected" folder. Your originals are not changed.',
        "",
        'cd "$(dirname "$0")" || exit 1',
        "shopt -s nullglob",
        "found=0; missing=0",
        "copy_photo() {",
        '  local dir="$1" base="$2" matched=0',
        '  for file in "./$dir/$base".*; do',
        '    mkdir -p -- "Selected/$dir" && cp -p -- "$file" "Selected/$dir/" && matched=1',
        "  done",
        '  if [ "$matched" = 1 ]; then found=$((found+1)); else missing=$((missing+1)); echo "Not found: $dir/$base"; fi',
        "}",
        "",
    ]
    for r in rows:
        lines.append(f"copy_photo {_sh_quote(r.folder or '.')} {_sh_quote(r.base_name)}")
    lines += [
        "",
        'echo "Copied $found of ' + str(len(rows)) + ' selected photos into the Selected folder."',
        'if [ "$missing" -gt 0 ]; then echo "$missing photos were not found. Is this the folder you uploaded?"; fi',
        "",
    ]
    return "\n".join(lines)


def _windows_script(event_title: str, client_name: str, rows: list[Row]) -> str:
    """The photo list lives in "::P|folder|name" data lines at the end of the script, read
    back with findstr. cmd expands FOR variables after it has parsed the line, so characters
    such as & | ( ) % ! in folder or file names are never run as commands. "|" cannot appear
    in Windows file names, so it is a safe separator.
    """
    lines = [
        "@echo off",
        f"rem {len(rows)} photos selected by {_comment_text(client_name)} for {_comment_text(event_title)}.",
        "rem Put this file in the event folder you uploaded, then double-click it.",
        'rem Copies are made in a new "Selected" folder. Your originals are not changed.',
        "setlocal DisableDelayedExpansion",
        "chcp 65001 >nul",
        'cd /d "%~dp0"',
        "set /a found=0, missing=0",
        'for /f "usebackq tokens=2,3 delims=|" %%A in (`findstr /b /c:"::P|" "%~f0"`) do (',
        '  if exist "%%A\\%%B.*" (',
        '    if not exist "Selected\\%%A\\" mkdir "Selected\\%%A"',
        '    copy /Y "%%A\\%%B.*" "Selected\\%%A\\" >nul',
        "    set /a found+=1",
        "  ) else (",
        '    echo Not found: "%%A\\%%B"',
        "    set /a missing+=1",
        "  )",
        ")",
        f"echo Copied %found% of {len(rows)} selected photos into the Selected folder.",
        "if %missing% gtr 0 echo %missing% photos were not found. Is this the folder you uploaded?",
        "pause",
        "exit /b",
        "",
        "rem Selected photos, one per line: folder, then name without extension.",
    ]
    for r in rows:
        folder = (r.folder or ".").replace("/", "\\")
        lines.append(f"::P|{folder}|{r.base_name}")
    lines.append("")
    return "\n".join(lines)
