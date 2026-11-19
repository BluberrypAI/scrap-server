"""Vendor replies the sender registers by hand; the server never sends or receives mail."""

import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT = 5000
MAX_REPLIES = 50
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,100}$")
_ZIP = (b"PK\x03\x04",)
FILE_TYPES = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "webp": ("image/webp", ()),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _ZIP),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", _ZIP),
    "hwpx": ("application/vnd.hancom.hwpx", _ZIP),
    "hwp": ("application/x-hwp", (b"\xd0\xcf\x11\xe0",)),
}


def clean_filename(name: str | None) -> str:
    base = re.split(r"[/\\]", name or "")[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip().strip(".")
    return base


def check_file(name: str | None, raw: bytes):
    """Return (clean_name, mime) or raise ValueError with a Korean message."""
    clean = clean_filename(name)
    ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
    if ext not in FILE_TYPES:
        raise ValueError("PDF·JPEG·PNG·WebP·XLSX·DOCX·HWP·HWPX 파일만 올릴 수 있습니다.")
    if not raw:
        raise ValueError("빈 파일은 올릴 수 없습니다.")
    mime, signatures = FILE_TYPES[ext]
    if ext == "webp":
        ok = raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    else:
        ok = any(raw.startswith(sig) for sig in signatures)
    if not ok:
        raise ValueError("파일 내용이 확장자와 맞지 않습니다.")
    if len(clean) > 200:
        stem = clean.rsplit(".", 1)[0]
        clean = stem[: 200 - len(ext) - 1] + "." + ext
    return clean, mime


def parse_received_on(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError("답장 받은 날은 YYYY-MM-DD 형식으로 적어 주세요.") from None
    if parsed > (datetime.now(UTC) + timedelta(hours=9)).date():
        raise ValueError("답장 받은 날이 미래일 수 없습니다.")
    return parsed


def attachment_disposition(name: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(name, safe='')}"
