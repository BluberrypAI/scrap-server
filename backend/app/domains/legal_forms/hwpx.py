"""Fill table cells of an original HWPX form without changing its layout.

Cells are `<hp:tc>` elements in `Contents/section0.xml`, addressed by order of
appearance. Each edit names the cell's original text (`expect`) so a changed
template stops with an error instead of filling the wrong cell.
"""

import io
import random
import re
import zipfile
from dataclasses import dataclass
from typing import Literal

SECTION = "Contents/section0.xml"
_TC = re.compile(r"<hp:tc\b.*?</hp:tc>", re.S)
_T = re.compile(r"<hp:t>(.*?)</hp:t>", re.S)
_PLAIN_T = re.compile(r"<hp:t>([^<]*)</hp:t>")
_RUN = re.compile(r'<hp:run charPrIDRef="(\d+)"')
_LINESEG = re.compile(r"<hp:linesegarray>.*?</hp:linesegarray>", re.S)


class TemplateMismatchError(Exception):
    """The template does not have the expected cell or text."""


@dataclass(frozen=True)
class CellEdit:
    cell: int
    expect: str
    op: Literal["append", "set", "sub", "image"]
    # set/append: text. sub: regex pattern and replacement text.
    # image: PNG placed in front of the paragraph whose run matches `pattern`.
    value: str
    pattern: str | None = None
    image: bytes | None = None
    # image size in HWPUNIT (1/7200 inch) and horizontal place in that paragraph
    image_size: tuple[int, int] = (0, 0)
    # where in the anchor paragraph: its right end by default (where "(서명 또는 인)" sits)
    image_align: Literal["LEFT", "CENTER", "RIGHT"] = "RIGHT"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _unesc(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _text_of(tc: str) -> str:
    return _unesc("".join(m.replace("<hp:lineBreak/>", "") for m in _T.findall(tc)))


def _first_para(tc: str) -> tuple[int, int]:
    s = tc.index("<hp:p ")
    return s, tc.index("</hp:p>", s)


def _append(tc: str, text: str) -> str:
    s, e = _first_para(tc)
    para = tc[s:e]
    runs = _RUN.findall(para)
    cp = runs[-1] if runs else "0"
    seg = para.rfind("<hp:linesegarray>")
    at = s + seg if seg >= 0 else e
    run = f'<hp:run charPrIDRef="{cp}"><hp:t>  {_esc(text)}</hp:t></hp:run>'
    return tc[:at] + run + tc[at:]


def _set(tc: str, text: str) -> str:
    s, e = _first_para(tc)
    para = tc[s:e]
    m = _RUN.search(para)
    cp = m.group(1) if m else "0"
    head = para[: para.index(">") + 1]
    # A line break keeps narrow cells from splitting numbers mid-way.
    body = _esc(text).replace("\n", "<hp:lineBreak/>")
    return tc[:s] + f'{head}<hp:run charPrIDRef="{cp}"><hp:t>{body}</hp:t></hp:run>' + tc[e:]


def _sub(tc: str, pattern: str, text: str) -> str:
    rx = re.compile(pattern)
    done = False

    def one(m: re.Match[str]) -> str:
        nonlocal done
        t = _unesc(m.group(1))
        if done or not rx.search(t):
            return m.group(0)
        done = True
        return f"<hp:t>{_esc(rx.sub(lambda _: text, t, count=1))}</hp:t>"

    out = _PLAIN_T.sub(one, tc)
    if not done:
        raise TemplateMismatchError(f"칸에서 바꿀 글자를 못 찾음: {pattern}")
    return out


_PARA = re.compile(r"<hp:p\b[^>]*>.*?</hp:p>", re.S)


def _pic(bin_id: str, w: int, h: int, align: str) -> str:
    """Floating picture in front of the text, hung from the top of its anchor paragraph.

    It moves with the text and does not change the layout. Hangul ignores negative offsets,
    so the picture cannot be lifted above the line; keep it small (see mark_box_cm).
    """
    pid, inst = random.randrange(10**9, 2 * 10**9), random.randrange(10**8, 10**9)
    return (
        f'<hp:pic id="{pid}" zOrder="100" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT" '
        f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" '
        f'instid="{inst}" reverse="0"><hp:offset x="0" y="0"/>'
        f'<hp:orgSz width="{w}" height="{h}"/><hp:curSz width="{w}" height="{h}"/>'
        '<hp:flip horizontal="0" vertical="0"/>'
        '<hp:rotationInfo angle="0" centerX="0" centerY="0" rotateimage="1"/>'
        '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
        f'<hc:img binaryItemIDRef="{bin_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{h}"/>'
        f'<hc:pt3 x="0" y="{h}"/></hp:imgRect>'
        '<hp:imgClip left="0" right="0" top="0" bottom="0"/>'
        '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:imgDim dimwidth="0" dimheight="0"/><hp:effects/>'
        f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" '
        'heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="1" '
        'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" '
        f'horzAlign="{align}" vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        "<hp:shapeComment>서명·날인</hp:shapeComment></hp:pic>"
    )


def _image(tc: str, pattern: str, pic: str) -> str:
    rx = re.compile(pattern)
    for m in _PARA.finditer(tc):
        if any(rx.search(_unesc(t)) for t in _PLAIN_T.findall(m.group(0))):
            para = m.group(0)
            head_end = para.index(">") + 1
            first = _RUN.search(para)
            cp = first.group(1) if first else "0"
            run = f'<hp:run charPrIDRef="{cp}">{pic}</hp:run>'
            return tc[: m.start()] + para[:head_end] + run + para[head_end:] + tc[m.end() :]
    raise TemplateMismatchError(f"칸에서 그림 자리를 못 찾음: {pattern}")


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def fill_hwpx(template: bytes, edits: list[CellEdit]) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(template))
    xml = src.read(SECTION).decode("utf-8")
    cells = list(_TC.finditer(xml))
    changed: dict[int, str] = {}
    # BinData items to add: name in the package -> PNG bytes
    used = {n for n in src.namelist() if n.startswith("BinData/")}
    images: dict[str, bytes] = {}
    for edit in edits:
        if edit.cell >= len(cells) or not _squash(_text_of(cells[edit.cell].group(0))).startswith(
            _squash(edit.expect)
        ):
            raise TemplateMismatchError(
                f'서식 칸 {edit.cell}이(가) "{edit.expect}"가 아님: 서식 파일이 바뀌었는지 확인'
            )
        tc = changed.get(edit.cell, cells[edit.cell].group(0))
        if edit.op == "append":
            tc = _append(tc, edit.value)
        elif edit.op == "set":
            tc = _set(tc, edit.value)
        elif edit.op == "image":
            n = 1
            while f"BinData/image{n}.png" in used or f"image{n}" in images:
                n += 1
            images[f"image{n}"] = edit.image or b""
            w, h = edit.image_size
            tc = _image(tc, edit.pattern or "", _pic(f"image{n}", w, h, edit.image_align))
        else:
            tc = _sub(tc, edit.pattern or "", edit.value)
        changed[edit.cell] = tc

    parts: list[str] = []
    last = 0
    for i, m in enumerate(cells):
        if i not in changed:
            continue
        # Drop the cached line layout of edited cells so Hangul lays them out again.
        parts.append(xml[last : m.start()] + _LINESEG.sub("", changed[i]))
        last = m.end()
    parts.append(xml[last:])

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        # HWPX rule: mimetype first and uncompressed.
        dst.writestr(zipfile.ZipInfo("mimetype"), src.read("mimetype"), zipfile.ZIP_STORED)
        for info in src.infolist():
            if info.filename == "mimetype" or info.is_dir():
                continue
            if info.filename == SECTION:
                data = "".join(parts).encode("utf-8")
            elif info.filename == MANIFEST and images:
                data = _with_items(src.read(info).decode("utf-8"), images).encode("utf-8")
            else:
                data = src.read(info)
            dst.writestr(info.filename, data, zipfile.ZIP_DEFLATED)
        for bin_id, png in images.items():
            # Pictures are stored uncompressed, as Hangul does.
            dst.writestr(f"BinData/{bin_id}.png", png, zipfile.ZIP_STORED)
    return out.getvalue()


MANIFEST = "Contents/content.hpf"


def _with_items(hpf: str, images: dict[str, bytes]) -> str:
    items = "".join(
        f'<opf:item id="{bin_id}" href="BinData/{bin_id}.png" media-type="image/png" '
        'isEmbeded="1"/>'
        for bin_id in images
    )
    if "</opf:manifest>" not in hpf:
        raise TemplateMismatchError("서식 파일 목록(content.hpf)에 manifest가 없음")
    return hpf.replace("</opf:manifest>", items + "</opf:manifest>", 1)


def hwpx_cells(file: bytes) -> list[str]:
    """Cell texts in order (for tests and checks)."""
    xml = zipfile.ZipFile(io.BytesIO(file)).read(SECTION).decode("utf-8")
    return [_text_of(m.group(0)) for m in _TC.finditer(xml)]


def hwpx_runs(file: bytes) -> list[list[str]]:
    """Text runs (<hp:t>) per cell, in order (layout measuring)."""
    xml = zipfile.ZipFile(io.BytesIO(file)).read(SECTION).decode("utf-8")
    return [[_unesc(t) for t in _PLAIN_T.findall(m.group(0))] for m in _TC.finditer(xml)]
