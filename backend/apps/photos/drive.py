"""Reading a shared Google Drive folder and turning its photos into PickSnap images.

Only folders shared as "Anyone with the link" can be read: the server uses an API key
(GOOGLE_API_KEY), not the studio's Google account. For each photo Google already has a
smaller copy (`thumbnailLink`), so the full original is never downloaded unless Google has
no such copy. The image is then made the same way the browser makes it on upload: one WebP
under MAX_IMAGE_BYTES, with the event's watermark.
"""

import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

API = "https://www.googleapis.com/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
MAX_FILES = 20_000
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
TIMEOUT = 30

IMAGE_LONG_EDGE = 1200
# (long edge, WebP quality) tried in order until the image fits. Small files matter more than
# clarity, but a photo shrunk too far is hard to judge, so quality drops before size does.
ATTEMPTS = (
    (1200, 75), (1200, 60), (1200, 50), (1200, 42),
    (1000, 42), (1000, 35), (880, 35), (880, 30),
    (760, 30), (640, 28), (560, 25), (480, 22), (400, 20),
)  # fmt: skip
# Google makes thumbnails of these; Pillow can open them when the original is downloaded.
DOWNLOADABLE = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff"}

_FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


class DriveError(Exception):
    """A problem the studio can fix (wrong link, folder not shared); the message says how."""


@dataclass
class DriveFile:
    id: str
    path: str  # relative to the shared folder, e.g. "Ceremony/IMG_0001.jpg"
    mime_type: str
    thumbnail_link: str
    size: int | None


def folder_id_from_link(link: str) -> str:
    """The folder ID from any usual Drive folder link, or the bare ID itself."""
    link = (link or "").strip()
    if _FOLDER_ID.match(link):
        return link
    parsed = urllib.parse.urlparse(link)
    if parsed.scheme not in ("http", "https") or not parsed.netloc.endswith("google.com"):
        raise DriveError(
            "Paste a Google Drive folder link (it starts with https://drive.google.com)."
        )
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
    folder_id = match.group(1) if match else urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
    if not _FOLDER_ID.match(folder_id):
        raise DriveError("This link does not point to a Google Drive folder.")
    return folder_id


def _get_json(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(
        {**params, "key": settings.GOOGLE_API_KEY, "supportsAllDrives": "true"}
    )
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "PickSnap"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise DriveError(
                "Could not open this folder. In Google Drive, choose Share, then set General "
                "access to “Anyone with the link”, and paste the link again."
            ) from error
        if error.code in (400, 403):
            raise DriveError(
                "Google refused the request. The folder may not be shared with anyone who has "
                "the link, or the import is not set up correctly on the server."
            ) from error
        raise


def list_folder(folder_id: str) -> tuple[str, list[DriveFile]]:
    """The folder's name and every image in it and its subfolders, sorted by path."""
    root = _get_json(f"{API}/{folder_id}", {"fields": "id,name,mimeType"})
    if root.get("mimeType") != FOLDER:
        raise DriveError(
            "This link is a file, not a folder. Share the folder that holds the photos."
        )
    files: list[DriveFile] = []
    pending = [(folder_id, "")]
    seen = {folder_id}
    while pending:
        current, prefix = pending.pop(0)
        token = None
        while True:
            params = {
                "q": f"'{current}' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,thumbnailLink,size,"
                "shortcutDetails(targetId,targetMimeType))",
                "pageSize": 1000,
                "includeItemsFromAllDrives": "true",
                "orderBy": "name_natural",
            }
            if token:
                params["pageToken"] = token
            page = _get_json(API, params)
            for item in page.get("files", []):
                name = _clean(item.get("name", ""))
                if not name:
                    continue
                mime = item.get("mimeType", "")
                if (
                    mime == SHORTCUT
                    and item.get("shortcutDetails", {}).get("targetMimeType") == FOLDER
                ):
                    mime, item = FOLDER, {**item, "id": item["shortcutDetails"]["targetId"]}
                if mime == FOLDER:
                    if item["id"] not in seen:
                        seen.add(item["id"])
                        pending.append((item["id"], f"{prefix}{name}/"))
                elif mime.startswith("image/"):
                    files.append(
                        DriveFile(
                            id=item["id"],
                            path=f"{prefix}{name}",
                            mime_type=mime,
                            thumbnail_link=item.get("thumbnailLink", ""),
                            size=int(item["size"]) if item.get("size") else None,
                        )
                    )
                    if len(files) > MAX_FILES:
                        raise DriveError(f"This folder has more than {MAX_FILES} photos.")
            token = page.get("nextPageToken")
            if not token:
                break
    files.sort(key=lambda f: f.path.lower())
    return _clean(root.get("name", "")), files


def _clean(name: str) -> str:
    """Drive allows any character in names; keep paths safe for the selection exports."""
    name = "".join(ch for ch in name if ch.isprintable())
    return re.sub(r'[|*?"<>/\\]', "_", name).strip()


def _fetch(url: str, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "PickSnap"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise DriveError("The file is too large to import.")
    return data


def source_image(file: DriveFile) -> bytes:
    """A copy of the photo at least IMAGE_LONG_EDGE wide: Google's own smaller copy when it
    has one, otherwise the original (only for kinds of image Pillow can open)."""
    sized = f"=s{IMAGE_LONG_EDGE}"
    candidates = []
    if file.thumbnail_link:
        candidates.append(re.sub(r"=s\d+(-[a-z0-9-]+)?$", sized, file.thumbnail_link))
    candidates.append(
        f"https://drive.google.com/thumbnail?id={urllib.parse.quote(file.id)}&sz=w{IMAGE_LONG_EDGE}"
    )
    for url in candidates:
        try:
            data = _fetch(url, limit=10 * 1024 * 1024)
        except (urllib.error.URLError, TimeoutError, DriveError):
            continue
        if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[8:12] == b"WEBP":
            return data
    if file.mime_type in DOWNLOADABLE and (file.size or 0) <= MAX_DOWNLOAD_BYTES:
        query = urllib.parse.urlencode({"alt": "media", "key": settings.GOOGLE_API_KEY})
        return _fetch(f"{API}/{urllib.parse.quote(file.id)}?{query}")
    raise DriveError("Google has no preview of this file (often the case for RAW files).")


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except (OSError, TypeError):  # Pillow built without FreeType
        return ImageFont.load_default()


def _draw(image: Image.Image, long_edge: int, watermark: str) -> Image.Image:
    scaled = image.copy()
    scaled.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    if watermark:
        width, height = scaled.size
        size = max(14, round(width * 0.03))
        layer = Image.new("RGBA", scaled.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(
            (width - size, height - size),
            watermark,
            font=_font(size),
            anchor="rd",
            fill=(255, 255, 255, 140),
            stroke_width=max(1, size // 14),
            stroke_fill=(0, 0, 0, 90),
        )
        scaled = Image.alpha_composite(scaled.convert("RGBA"), layer).convert("RGB")
    return scaled


def make_image(data: bytes, watermark: str = "") -> tuple[bytes, int, int]:
    """One WebP under MAX_IMAGE_BYTES: the largest size and best quality that fit."""
    with Image.open(io.BytesIO(data)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    limit = settings.MAX_IMAGE_BYTES
    drawn: dict[int, Image.Image] = {}
    for edge, quality in ATTEMPTS:
        if edge not in drawn:
            drawn[edge] = _draw(image, edge, watermark)
        out = io.BytesIO()
        drawn[edge].save(out, "WEBP", quality=quality, method=4)
        if out.tell() <= limit:
            return out.getvalue(), drawn[edge].width, drawn[edge].height
    raise DriveError(f"Could not make this photo smaller than {limit // 1024} KB.")
