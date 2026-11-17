"""Draw filled values on the blank form PDF (rendered once by Hancom from the same HWPX).

Positions come from `<kind>-layout.json`, measured by scrap-documents/scripts/build-preview.mjs
(units: pt, origin top-left, page 1 only). Rebuild both when a template changes.
Slot kinds: tick (checkbox, no cell), set (whole cell), append (after the cell label),
line group (a line with inline blanks is redrawn with the values substituted).
"""

import io
import re
from functools import cache

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import black, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.domains.legal_forms.service import RESOURCES, Edit, mark_box_cm, read_layout

PT_PER_CM = 72 / 2.54

# A bundled open-licence TTF (resources/fonts/*.ttf) is embedded when present.
# Otherwise the standard Adobe Korean font is referenced and the viewer supplies it
# (spacing of digits/hyphens may then differ by viewer).
_TTF = sorted((RESOURCES / "fonts").glob("*.ttf")) if (RESOURCES / "fonts").is_dir() else []
if _TTF:
    FONT = "FormFont"
    pdfmetrics.registerFont(TTFont(FONT, str(_TTF[0])))
else:
    FONT = "HYGothic-Medium"
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))
LEADING = 1.2
MIN_SIZE = 4.0


class LayoutMissingError(Exception):
    """An edit has no measured position (layout data is older than the template rules)."""


def _layout(kind: str) -> dict:
    return read_layout(kind)


@cache
def _blank(kind: str) -> bytes:
    return (RESOURCES / f"{kind}-blank.pdf").read_bytes()


def _w(text: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, FONT, size)


def _wrap(text: str, width: float, size: float, first: float | None = None) -> list[str]:
    """Break by characters to fit `width` (`first`: width of the first line)."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            limit = first if first is not None and not lines else width
            if cur and _w(cur + ch, size) > limit:
                lines.append(cur)
                cur = ch.lstrip()
            else:
                cur += ch
        lines.append(cur)
    return lines


def _fit(text: str, width: float, height: float, size: float) -> tuple[list[str], float]:
    """Largest size (<= measured size) whose wrapped lines fit the cell."""
    s = size
    while True:
        lines = _wrap(text, width, s)
        if len(lines) * s * LEADING <= height or s <= MIN_SIZE:
            return lines, s
        s -= 0.25


class _Page:
    def __init__(self, c: Canvas, height: float):
        self.c, self.h = c, height

    def cover(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.c.setFillColor(white)
        self.c.rect(x0, self.h - y1, x1 - x0, y1 - y0, stroke=0, fill=1)
        self.c.setFillColor(black)

    def text(self, x: float, top: float, s: str, size: float) -> None:
        # `top` is the top of the line box; place the baseline about 0.85 em below it.
        self.c.setFont(FONT, size)
        self.c.drawString(x, self.h - top - size * 0.85, s)


def _draw_set(p: _Page, slot: dict, show: str) -> None:
    x0, y0, x1, y1 = slot["cell"]
    pad = 1.5
    p.cover(x0 + 1, y0 + 1, x1 - 1, y1 - 1)
    lines, size = _fit(show, x1 - x0 - 2 * pad, y1 - y0 - 2, slot["size"])
    top = y0 + (y1 - y0 - len(lines) * size * LEADING) / 2
    for i, line in enumerate(lines):
        w = _w(line, size)
        x = x0 + (x1 - x0 - w) / 2 if slot.get("align") == "center" else x0 + pad
        p.text(x, top + i * size * LEADING, line, size)


def _draw_append(p: _Page, slot: dict, show: str) -> None:
    bx0, by0 = slot["box"][:2]
    cx0, _, cx1, cy1 = slot["cell"]
    pad = 4
    size = slot["size"]
    while True:
        lines = _wrap(show, cx1 - cx0 - 2 * pad, size, first=cx1 - pad - bx0)
        if by0 + len(lines) * size * LEADING <= cy1 - 1 or size <= MIN_SIZE:
            break
        size -= 0.25
    for i, line in enumerate(lines):
        x = bx0 if i == 0 else cx0 + pad
        p.text(x, by0 + i * size * LEADING, line, size)


def _draw_line(p: _Page, group: dict, edits: list[Edit]) -> None:
    text = group["orig"]
    for e in edits:
        text = re.sub(e.pattern or "", lambda _, e=e: e.before + e.show + e.after, text, count=1)
    # Only the run holding the value is redrawn; other text on the line (e.g. "귀하") stays.
    lx0, ly0, lx1, ly1 = group["box"]
    rx0, _, rx1, _ = group.get("run", group["box"])
    cx0, _, cx1, _ = group["cell"]
    size = group["size"]
    right = group.get("align") == "right"
    tail = group.get("tail")
    room = (rx1 - cx0 - 2) if right else (cx1 - rx0 - 2)
    if tail and not right:
        # leave space for the tail text that follows the value (e.g. "  귀하")
        tx0, ty0, tx1, ty1 = group["tail_box"]
        tail_size = (ty1 - ty0) * 0.85
        room -= _w("  " + tail, tail_size)
    while _w(text, size) > room and size > MIN_SIZE:
        size -= 0.25
    w = _w(text, size)
    x = rx1 - w if right else rx0
    end = group["tail_box"][2] if tail and not right else max(x + w, rx1)
    p.cover(min(x, rx0) - 1, ly0 - 0.5, end + 1, ly1 + 0.5)
    p.text(x, ly0, text, size)
    if tail and not right:
        # move the tail right after the new value, on its own baseline and size
        p.text(x + w + _w("  ", tail_size), ty0, tail, tail_size)


def _draw_signature(p: _Page, slot: dict, png: bytes, mark_type: str) -> None:
    """Place the signature/seal centred over "(서명 또는 인)", same size as in the HWPX file."""
    x0, y0, x1, y1 = slot["box"]
    img = ImageReader(io.BytesIO(png))
    w_cm, h_cm = mark_box_cm(png, mark_type)
    w, h = w_cm * PT_PER_CM, h_cm * PT_PER_CM
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    p.c.drawImage(img, cx - w / 2, p.h - cy - h / 2, w, h, mask="auto")


def form_pdf(
    kind: str, edits: list[Edit], signature: bytes | None = None, mark_type: str = "signature"
) -> bytes:
    layout = _layout(kind)
    slots, groups = layout["slots"], layout.get("groups", {})
    width, height = layout["page"]
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(width, height))
    page = _Page(c, height)
    lines: dict[str, list[Edit]] = {}
    signs: list[dict] = []
    for e in edits:
        if e.op == "sign" and not signature:
            continue
        slot = slots.get(e.slot)
        if slot is None:
            raise LayoutMissingError(
                f"서식 칸 {e.slot}의 위치 자료가 없음: 미리보기 자료를 다시 만드세요"
            )
        if e.op == "sign":
            signs.append(slot)
        elif "group" in slot:
            lines.setdefault(slot["group"], []).append(e)
        elif e.place == "at":
            x0, y0 = slot["box"][:2]
            # The box is where the value itself starts (measured with the same padding).
            page.text(x0, y0, e.show, slot["size"])
        elif "cell" not in slot:
            x0, y0 = slot["box"][:2]
            page.text(x0, y0, "√", slot["size"])
        elif e.op == "set":
            _draw_set(page, slot, e.show)
        else:
            _draw_append(page, slot, e.show)
    for g, es in lines.items():
        _draw_line(page, groups[g], es)
    for slot in signs:  # last, so the signature sits on top of redrawn lines
        _draw_signature(page, slot, signature or b"", mark_type)
    c.save()

    overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_blank(kind))))
    writer.pages[0].merge_page(overlay)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
