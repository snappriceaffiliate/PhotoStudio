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
        name = self.filename
        return name.rsplit(".", 1)[0] if "." in name else name


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
                r.folder,
                r.filename,
                r.relative_path,
                r.album,
                r.note,
                timezone.localtime(r.selected_at).strftime("%Y-%m-%d %H:%M"),
                r.photo_id,
            ]
        )
    return ("﻿" + out.getvalue()).encode()  # BOM so Excel reads UTF-8 names correctly


def _lightroom(rows: list[Row]) -> str:
    """Paste into Lightroom Classic: Library Filter > Text > Filename > Contains."""
    names = list(dict.fromkeys(r.base_name for r in rows))
    return ", ".join(names) + "\n"


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _mac_script(event_title: str, client_name: str, rows: list[Row]) -> str:
    lines = [
        "#!/bin/bash",
        f"# {len(rows)} photos selected by {client_name} for {event_title}.",
        "# Put this file in the event folder you uploaded, then in Terminal run:",
        "#   bash copy-selected.sh",
        '# Copies are made in a new "Selected" folder. Your originals are not changed.',
        "",
        'cd "$(dirname "$0")" || exit 1',
        "shopt -s nullglob",
        "found=0; missing=0",
        "copy_photo() {",
        '  local dir="$1" base="$2" matched=0',
        '  for file in "$dir/$base".*; do',
        '    mkdir -p "Selected/$dir" && cp -p "$file" "Selected/$dir/" && matched=1',
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


def _cmd_quote(value: str) -> str:
    # Inside double quotes cmd still expands %VAR%; double the % signs to keep them literal.
    return '"' + value.replace("%", "%%").replace('"', "") + '"'


def _windows_script(event_title: str, client_name: str, rows: list[Row]) -> str:
    lines = [
        "@echo off",
        f"rem {len(rows)} photos selected by {client_name} for {event_title}.",
        "rem Put this file in the event folder you uploaded, then double-click it.",
        'rem Copies are made in a new "Selected" folder. Your originals are not changed.',
        "chcp 65001 >nul",
        'cd /d "%~dp0"',
        "set found=0",
        "set missing=0",
        "",
    ]
    for r in rows:
        folder = (r.folder or ".").replace("/", "\\")
        lines.append(f"call :copy_photo {_cmd_quote(folder)} {_cmd_quote(r.base_name)}")
    lines += [
        "",
        f"echo Copied %found% of {len(rows)} selected photos into the Selected folder.",
        "if %missing% gtr 0 echo %missing% photos were not found. Is this the folder you uploaded?",
        "pause",
        "exit /b",
        "",
        ":copy_photo",
        'if exist "%~1\\%~2.*" (',
        '  if not exist "Selected\\%~1" mkdir "Selected\\%~1"',
        '  copy /Y "%~1\\%~2.*" "Selected\\%~1\\" >nul',
        "  set /a found+=1",
        ") else (",
        "  echo Not found: %~1\\%~2",
        "  set /a missing+=1",
        ")",
        "exit /b",
        "",
    ]
    return "\n".join(lines)
