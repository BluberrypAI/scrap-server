"""Fill table cells of an original HWPX form without changing its layout.

Cells are `<hp:tc>` elements in `Contents/section0.xml`, addressed by order of
appearance. Each edit names the cell's original text (`expect`) so a changed
template stops with an error instead of filling the wrong cell.
"""

import io
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
    op: Literal["append", "set", "sub"]
    # set/append: text. sub: regex pattern and replacement text.
    value: str
    pattern: str | None = None


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


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def fill_hwpx(template: bytes, edits: list[CellEdit]) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(template))
    xml = src.read(SECTION).decode("utf-8")
    cells = list(_TC.finditer(xml))
    changed: dict[int, str] = {}
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
            data = "".join(parts).encode("utf-8") if info.filename == SECTION else src.read(info)
            dst.writestr(info.filename, data, zipfile.ZIP_DEFLATED)
    return out.getvalue()


def hwpx_cells(file: bytes) -> list[str]:
    """Cell texts in order (for tests and checks)."""
    xml = zipfile.ZipFile(io.BytesIO(file)).read(SECTION).decode("utf-8")
    return [_text_of(m.group(0)) for m in _TC.finditer(xml)]


def hwpx_runs(file: bytes) -> list[list[str]]:
    """Text runs (<hp:t>) per cell, in order (layout measuring)."""
    xml = zipfile.ZipFile(io.BytesIO(file)).read(SECTION).decode("utf-8")
    return [[_unesc(t) for t in _PLAIN_T.findall(m.group(0))] for m in _TC.finditer(xml)]
