# ruff: noqa: E501  (PowerShell 명령과 한국어 설명 줄)
"""법정 서식 칸 위치 자료 만들기 (개발용. Windows + 한컴오피스 필요).

서식 파일이나 칸 규칙(app/domains/legal_forms/service.py)을 바꿨을 때만 다시 돌린다.

    uv run --project backend --with pymupdf python scripts/legal_forms_layout.py [--png 웹폴더]

하는 일
1. 값이 다 찬 가상 입력으로, 칸마다 값 대신 표시 글자(Q00Q)를 넣은 한글 파일을 만든다
2. 한컴오피스로 PDF로 바꾼다 (빈 서식도 같이 → resources/<kind>-blank.pdf)
3. 표시 글자 위치와 그 칸의 테두리를 재서 resources/<kind>-layout.json에 쓴다 (pt, 왼쪽 위 기준, 첫 쪽)
4. --png를 주면 빈 서식 첫 쪽 그림(<kind>.png, 144dpi)을 그 폴더에 쓴다 (웹 미리보기용)

칸 종류
- mark: 빈 칸·칸 이름 뒤 → 표시 글자 위치와 칸 테두리
- check: [ ] 체크 → 실제 √를 넣어 위치를 잰다
- line: 줄 중간의 빈자리(산업단지명, 날짜, 받는 기관 등) → 그 줄 전체를 다시 그린다
- at: 빈칸 덩어리에 쓰는 값(제12호 제출인 이름) → 표시 글자 위치에 그대로 쓴다
- sign: 서명 이미지 위치 → "(서명 또는 인)" 자리
"""

import argparse
import base64
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domains.legal_forms import service  # noqa: E402
from app.domains.legal_forms.hwpx import hwpx_runs  # noqa: E402
from app.domains.legal_forms.schemas import (  # noqa: E402
    FormCompanyIn,
    FormSubmitIn,
    FormWasteIn,
)

# 1x1 투명 PNG (서명 칸 위치만 재므로 내용은 상관없다)
DOT = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000000000200015e2d3b0f0000000049454e44ae426082"
    )
).decode()

COMPANY = FormCompanyIn(
    name="(가상)측정회사",
    business_registration_number="123-45-67890",
    representative_name="홍길동",
    address="경기도 화성시 측정로 1",
    industrial_complex_name="측정산단",
    phone="031-000-0000",
    industry="측정 업종",
    raw_material="원료 1톤/년",
    main_product="제품 1톤/년",
    process_flow="입고 - 가공 - 출하",
)
SUBMIT = FormSubmitIn(
    date=datetime.date(2026, 1, 1),
    recipient="",  # 종류별로 채움
    signer_name="홍길동",
    signature_png=f"data:image/png;base64,{DOT}",
    signer_confirmed=True,
)
HANDOFF = {
    "result_type": "WASTE_CODE",
    "review": "VERIFIED",
    "facts": {"physical_state": {"value": "solid", "source_type": "UTTERANCE"}},
}
GENERAL = {**HANDOFF, "waste_code": "51-03-01", "waste_name": "폐합성수지류", "category": "GENERAL"}
DESIGNATED = {**HANDOFF, "waste_code": "02-01-01", "waste_name": "폐염산", "category": "DESIGNATED"}
WASTE = FormWasteIn(
    group=1,
    designated_kind="폐산",
    tons_per_month=1,
    kg_per_month=1000,
    tons_per_year=12,
    frequency="1회/월",
    carrier="측정운반",
    carried_tons=12,
    treatment="위탁",
    vendor="측정처리",
    method="2003",
    treated_tons_per_year=12,
)
# 제12호 운반방법은 자가·위탁 두 번 잰다
PROBES = {
    "form6": [(GENERAL, WASTE, "화성시장")],
    "form12": [
        (DESIGNATED, WASTE.model_copy(update={"method": "2116"}), "경기도지사"),
        (DESIGNATED, WASTE.model_copy(update={"method": "2116", "carrier": "자가"}), "경기도지사"),
    ],
    "form5": [(GENERAL, WASTE, "")],
}


def plan(kind, edits, runs):
    """편집마다 측정 방법과 표시 글자."""
    text_sub_cells = {e.cell for e in edits if e.op == "sub" and e.show != "√"}
    slots, n = {}, 0

    def tok():
        nonlocal n
        n += 1
        return f"Q{n - 1:02d}Q"

    for e in edits:
        if e.op == "sign":
            slots[e.slot] = {"type": "sign", "tok": tok()}
        elif e.op != "sub":
            slots[e.slot] = {"type": "mark", "tok": tok()}
        elif e.place == "at":
            slots[e.slot] = {"type": "at", "tok": tok()}
        elif e.cell not in text_sub_cells:
            slots[e.slot] = {"type": "check"}
        else:
            r = next(i for i, t in enumerate(runs[e.cell]) if re.search(e.pattern or "", t))
            x = {"type": "line", "group": f"{e.cell}:{r}", "orig": runs[e.cell][r]}
            if e.show != "√":
                x["tok"] = tok()
            slots[e.slot] = x
    return slots


def build_probes(work: Path) -> dict:
    marks = {}
    for kind, cases in PROBES.items():
        template = service.read_template(kind)
        runs = hwpx_runs(template)
        (work / f"{kind}-blank.hwpx").write_bytes(template)
        marks[kind] = []
        for i, (handoff, waste, recipient) in enumerate(cases):
            verdict = service.verdict_from(handoff, waste)
            # 제5호의 날짜·서명은 수탁자 몫이라 채우지 않는다
            submit = (
                FormSubmitIn()
                if kind == "form5"
                else SUBMIT.model_copy(update={"recipient": recipient})
            )
            company = service.company_from(None, COMPANY)
            edits = service.form_edits(kind, verdict, company, waste, submit)
            slots = plan(kind, edits, runs)
            data = service.form_hwpx(kind, edits, mark=lambda e, s=slots: s[e.slot].get("tok"))
            (work / f"{kind}-probe{i}.hwpx").write_bytes(data)
            marks[kind].append(slots)
    return marks


PS = r"""
param([string]$Dir)
$tmp = Join-Path $env:TEMP "legal-forms-layout"
New-Item -ItemType Directory -Force $tmp | Out-Null
$i = 0
foreach ($f in Get-ChildItem $Dir -Filter *.hwpx) {
  $i++
  $src = Join-Path $tmp "f$i.hwpx"; $pdf = Join-Path $tmp "f$i.pdf"
  Copy-Item $f.FullName $src -Force
  $job = Start-Job { param($s, $p) $h = New-Object -ComObject HWPFrame.HwpObject; $o = $h.Open($s, "", "forceopen:true"); $r = $h.SaveAs($p, "PDF", ""); $h.Quit(); "$o $r" } -ArgumentList $src, $pdf
  if (Wait-Job $job -Timeout 60) { Receive-Job $job | Out-Null; Move-Item $pdf ($f.FullName -replace '\.hwpx$', '.pdf') -Force; "$($f.Name) ok" }
  else { Stop-Job $job; Get-Process Hwp -ErrorAction SilentlyContinue | Stop-Process -Force; "$($f.Name) timeout" }
}
"""


def to_pdf(work: Path) -> None:
    # 한글 COM은 한글 경로에서 멈추는 일이 있어 영문 임시 이름으로 바꿔 변환한다
    ps = work / "convert.ps1"
    ps.write_text(PS, encoding="utf-8-sig")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), str(work)],
        check=True,
    )


# ---- 측정 (PyMuPDF) ----


def measure(work: Path, marks: dict, png_dir: Path | None) -> None:
    import fitz

    def lines(page):
        v, h = [], []
        for d in page.get_drawings():
            for it in d["items"]:
                if it[0] == "l":
                    a, b = it[1], it[2]
                    if abs(a.x - b.x) < 0.5:
                        v.append((a.x, min(a.y, b.y), max(a.y, b.y)))
                    elif abs(a.y - b.y) < 0.5:
                        h.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif it[0] == "re":
                    r = it[1]
                    if r.width < 1.5:
                        v.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                    elif r.height < 1.5:
                        h.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                    else:
                        v += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
                        h += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
        return v, h

    def cell_of(box, v, h, page):
        # 표 바깥 세로선이 없으면 가로선 끝을 칸 끝으로 본다
        left_edge = min((x0 for _, x0, _ in h), default=0)
        right_edge = max((x1 for _, _, x1 in h), default=page.rect.width)
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        left = max(
            [x for x, y0, y1 in v if x <= box[0] + 0.5 and y0 - 1 <= cy <= y1 + 1],
            default=left_edge,
        )
        right = min(
            [x for x, y0, y1 in v if x >= box[2] - 0.5 and y0 - 1 <= cy <= y1 + 1],
            default=right_edge,
        )
        top = max([y for y, x0, x1 in h if y <= box[1] + 0.5 and x0 - 1 <= cx <= x1 + 1], default=0)
        bottom = min(
            [y for y, x0, x1 in h if y >= box[3] - 0.5 and x0 - 1 <= cx <= x1 + 1],
            default=page.rect.height,
        )
        return [left, top, right, bottom]

    def text_lines(page):
        out = []
        for b in page.get_text("rawdict")["blocks"]:
            for ln in b.get("lines", []):
                cs = [c for sp in ln["spans"] for c in sp["chars"]]
                if cs:
                    out.append(("".join(c["c"] for c in cs), [c["bbox"] for c in cs], ln["bbox"]))
        return out

    def find(lines_, needle):
        hits = []
        for t, bbs, lb in lines_:
            k = t.find(needle)
            while k >= 0:
                sel = bbs[k : k + len(needle)]
                box = [
                    min(b[0] for b in sel),
                    min(b[1] for b in sel),
                    max(b[2] for b in sel),
                    max(b[3] for b in sel),
                ]
                hits.append((box, lb))
                k = t.find(needle, k + 1)
        return hits

    def r1(xs):
        return [round(x, 1) for x in xs]

    def squash(t):
        return re.sub(r"\s+", "", t)

    res = service.RESOURCES
    for kind, probes in marks.items():
        doc = fitz.open(work / f"{kind}-blank.pdf")
        blank = doc[0]
        shutil.copyfile(work / f"{kind}-blank.pdf", res / f"{kind}-blank.pdf")
        v, h = lines(blank)
        blank_lines = text_lines(blank)
        if png_dir:
            blank.get_pixmap(dpi=144).save(str(png_dir / f"{kind}.png"))
        slots, groups = {}, {}
        printed = [b for b, _ in find(blank_lines, "√")]
        for i, m in enumerate(probes):
            page = fitz.open(work / f"{kind}-probe{i}.pdf")[0]
            pl = text_lines(page)
            ticks = sorted(
                (
                    b
                    for b, _ in find(pl, "√")
                    if not any(abs(b[0] - p[0]) < 2 and abs(b[1] - p[1]) < 2 for p in printed)
                ),
                key=lambda b: (round(b[1]), b[0]),
            )
            checks = sorted(
                (k for k, x in m.items() if x["type"] == "check"),
                key=lambda k: [int(p) for p in k.split(".")],
            )
            if len(ticks) < len(checks):
                print(f"{kind}: √ {len(ticks)}개, 체크 칸 {len(checks)}개가 안 맞음")
            for k, b in zip(checks, ticks, strict=False):
                slots[k] = {"box": r1(b), "size": round((b[3] - b[1]) * 0.9, 1)}
            for slot, x in m.items():
                if x["type"] == "check":
                    continue
                b = c = None
                if "tok" in x:
                    hit = find(pl, x["tok"])
                    if not hit:
                        print(f"{kind} {slot}: 표시 글자 {x['tok']}를 못 찾음")
                        continue
                    b = hit[0][0]
                    c = cell_of(b, v, h, blank)
                size = round((b[3] - b[1]) * 0.85, 1) if b else None
                if x["type"] == "mark":
                    mid = (b[0] + b[2]) / 2
                    slots[slot] = {
                        "box": r1(b),
                        "cell": r1(c),
                        "size": size,
                        "align": "center" if abs(mid - (c[0] + c[2]) / 2) < 3 else "left",
                    }
                    continue
                if x["type"] in ("at", "sign"):
                    slots[slot] = {"box": r1(b), "size": size, x["type"]: True}
                    continue
                slots[slot] = {"group": x["group"]}
                g = x["group"]
                if g in groups or c is None:
                    continue
                head = squash(x["orig"])[:6]
                cands = [
                    (t, bbs, lb)
                    for t, bbs, lb in blank_lines
                    if head
                    and head in squash(t)
                    and c[0] - 1 <= lb[0]
                    and lb[2] <= c[2] + 1
                    and c[1] - 1 <= lb[1]
                    and lb[3] <= c[3] + 1
                ]
                if not cands:
                    print(f"{kind} {slot}: 빈 서식에서 줄을 못 찾음 {head}")
                    continue
                t, bbs, lb = cands[0]
                # 이 값이 들어가는 글자 덩어리(run)만의 상자: 같은 줄의 다른 글자(예: "귀하")는 그대로 둔다
                idx = [i for i, ch in enumerate(t) if not ch.isspace()]
                k = "".join(t[i] for i in idx).find(squash(x["orig"]))
                run_box, tail, tail_box = lb, "", None
                if k >= 0 and squash(x["orig"]):
                    end = k + len(squash(x["orig"]))
                    sel = [bbs[i] for i in idx[k:end]]
                    run_box = [
                        min(b[0] for b in sel),
                        min(b[1] for b in sel),
                        max(b[2] for b in sel),
                        max(b[3] for b in sel),
                    ]
                    # 같은 줄에서 값 뒤에 오는 글자(예: "귀하"): 값 길이가 바뀌면 붙여서 다시 그린다
                    rest = idx[end:]
                    if rest:
                        tail = t[rest[0] :].strip()
                        tb = [bbs[i] for i in rest]
                        tail_box = [
                            min(b[0] for b in tb),
                            min(b[1] for b in tb),
                            max(b[2] for b in tb),
                            max(b[3] for b in tb),
                        ]
                groups[g] = {
                    "orig": x["orig"],
                    "run": r1(run_box),
                    **({"tail": tail, "tail_box": r1(tail_box)} if tail else {}),
                    "box": r1(lb),
                    "cell": r1(c),
                    "size": round((lb[3] - lb[1]) * 0.85, 1),
                    "align": "right" if c[2] - lb[2] < 8 and lb[0] - c[0] > 20 else "left",
                }
        out = {"page": [blank.rect.width, blank.rect.height], "slots": slots, "groups": groups}
        (res / f"{kind}-layout.json").write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8"
        )
        print(kind, len(slots), "칸,", len(groups), "줄")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", type=Path, help="빈 서식 첫 쪽 그림을 쓸 폴더 (웹 미리보기용)")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        marks = build_probes(work)
        to_pdf(work)
        measure(work, marks, args.png)


if __name__ == "__main__":
    main()
