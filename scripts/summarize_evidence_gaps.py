"""Compare historical missing-evidence rows with a newly recorded model review.

Old reviews did not persist a cause. Never infer a historical model rationale.
Only store public capability identifiers and outcome categories in the report.
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def key(material, detail, form, capability):
    return material, detail, form, capability


def summarize(baseline, current, catalog):
    capabilities = {row["key"]: row for row in catalog["capabilities"]}
    facilities = {row["key"]: row for row in catalog["facilities"]}
    sources = {row["key"]: row for row in catalog["sources"]}
    lookup = {}
    for batch in current["results"]:
        for capability, review in (
            (batch.get("response", {}).get("reviews") or {}).get("results", {}).items()
        ):
            lookup[
                key(
                    batch["material"],
                    batch.get("material_detail"),
                    batch["form"],
                    capability,
                )
            ] = review
    rows = []
    for old in baseline["rows"]:
        capability = capabilities[old["capability_key"]]
        input_source_ids = capability.get("input_profile", {}).get("source_ids", [])
        site = facilities[capability["facility"]]
        review = lookup.get(
            key(
                old["diagnosis_material"],
                old.get("material_detail"),
                old["form"],
                old["capability_key"],
            )
        )
        rows.append(
            {
                **old,
                "facility_key": site["key"],
                "facility_name": site["label"],
                "historical_cause": "not_recorded",
                "current_status": review["status"] if review else "not_retested",
                "current_evidence_gaps": review.get("evidence_gaps", [])
                if review
                else [],
                "source_ids": capability["source_ids"],
                "input_source_ids": input_source_ids,
                "eligible_source_ids": [
                    sid
                    for sid in input_source_ids
                    if sources[sid].get("model_transfer_allowed")
                ],
                "withheld_source_ids": [
                    sid
                    for sid in input_source_ids
                    if not sources[sid].get("model_transfer_allowed")
                ],
            }
        )
    return {
        "scope": "252 historical review occurrences, not 252 facilities; current causes are NEW re-review results, not reconstructed historical model rationale",
        "baseline_occurrences": len(rows),
        "baseline_distinct_capabilities": len({r["capability_key"] for r in rows}),
        "baseline_distinct_facilities": len({r["facility_key"] for r in rows}),
        "current_status_counts": dict(Counter(r["current_status"] for r in rows)),
        "primary_gap_counts": dict(
            Counter(
                (r["current_evidence_gaps"] or ["unspecified"])[0]
                for r in rows
                if r["current_status"] == "needs_evidence"
            )
        ),
        "all_gap_counts_multiple_allowed": dict(
            Counter(
                gap
                for r in rows
                if r["current_status"] == "needs_evidence"
                for gap in set(r["current_evidence_gaps"] or ["unspecified"])
            )
        ),
        "rows": rows,
    }


def markdown(report):
    labels = {
        "input_form_unproven": (
            "투입 형태",
            "스크랩·경질품·필름·파쇄품 등 이번 형태의 반입 사례·규격",
        ),
        "material_unproven": (
            "재질",
            "PP/PE/PS 등 정확한 수지를 이 사업장에서 처리한다는 자료",
        ),
        "output_only": (
            "생산품만 소개",
            "펠릿 판매 설명 대신 무엇을 투입해 만드는지 보여 주는 공정 자료",
        ),
        "process_unproven": (
            "공정",
            "필요한 선별·세척·파쇄·재생 공정을 수행하는 현장 자료",
        ),
        "site_scope_unverified": (
            "사업장",
            "본사나 여러 공장 중 어느 주소의 사업장이 수행하는지",
        ),
        "source_missing": (
            "AI에 전달된 적용 근거 없음",
            "전송 가능한 공식 근거. 아래 전송 제외 자료와 구분",
        ),
        "source_context_conflict": (
            "문맥 상충",
            "반입 제한 문장을 포함한 원문 전체 문맥",
        ),
        "citation_invalid": (
            "인용 대조 실패",
            "실제 요약에 존재하는 인용과 대상 사업장 재대조",
        ),
        "unspecified": ("구분 불가", "원문 재검토 또는 업체 확인"),
    }
    lines = [
        "# 기존 근거 부족 252회의 재검토",
        "",
        f"252회는 **{report['baseline_distinct_facilities']}개 사업장·{report['baseline_distinct_capabilities']}개 공정 연결**의 형태별 반복 검토입니다. 252개 업체가 아닙니다.",
        "과거 응답은 원인을 저장하지 않았습니다. 아래는 보강 이후 **새 AI 검토와 코드 검사에서 나온 사유**이며 과거 판단의 복원이 아닙니다.",
        "",
        "## 새 결과",
        "",
        "| 상태 | 횟수 |",
        "| --- | ---: |",
    ]
    lines += [
        f"| {status} | {count} |"
        for status, count in report["current_status_counts"].items()
    ]
    lines += [
        "",
        "## 무엇이 부족한가",
        "",
        "첫 사유는 각 needs_evidence 결과의 첫 항목입니다. 한 결과에 여러 이유가 있어 전체 사유 횟수는 중복 집계입니다.",
        "",
        "| 부족한 항목 | 첫 사유 횟수 | 중복 포함 횟수 | 채울 자료 |",
        "| --- | ---: | ---: | --- |",
    ]
    for gap, count in sorted(
        report["all_gap_counts_multiple_allowed"].items(), key=lambda item: -item[1]
    ):
        label, action = labels[gap]
        lines.append(
            f"| {label} | {report['primary_gap_counts'].get(gap, 0)} | {count} | {action} |"
        )
    withheld_sites = sorted(
        {
            r["facility_name"]
            for r in report["rows"]
            if r["withheld_source_ids"] and not r["eligible_source_ids"]
        }
    )
    lines += [
        "",
        "## 자료가 있어도 AI에 못 보낸 경우",
        "",
        "현재 참조에서 전송 가능한 출처가 하나도 없는 사업장: "
        + (", ".join(withheld_sites) or "없음")
        + ".",
        "이는 회사 자료가 세상에 없다는 뜻이 아닙니다. 전송 제한을 자동 해제하지 않습니다. 행별 JSON의 eligible_source_ids / withheld_source_ids로 구분할 수 있습니다.",
        "",
        "## 사업장별 현재 결과",
        "",
        "| 사업장 | 해당 검토 횟수 | 결과 | 부족 사유(중복) |",
        "| --- | ---: | --- | --- |",
    ]
    for name in sorted({r["facility_name"] for r in report["rows"]}):
        rows = [r for r in report["rows"] if r["facility_name"] == name]
        statuses = Counter(r["current_status"] for r in rows)
        gaps = Counter(
            g
            for r in rows
            if r["current_status"] == "needs_evidence"
            for g in set(r["current_evidence_gaps"] or ["unspecified"])
        )
        lines.append(
            f"| {name} | {len(rows)} | "
            + ", ".join(f"{k} {v}" for k, v in statuses.items())
            + " | "
            + ", ".join(f"{labels[k][0]} {v}" for k, v in gaps.items())
            + " |"
        )
    lines += [
        "",
        "reviewed도 이번 물량의 반입 승인·현행 허가·법적 정답 검증을 뜻하지 않습니다. 오류나 미완료를 근거 부족으로 합산하지 않습니다.",
        "",
        "[252행 상세 JSON](intake-evidence-gaps-20261116.json) · [추가한 공개 근거와 남은 소재](remaining-material-evidence-20261116.md) · [전체 연결 검사](../flow-audit-20261116.md)",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    report = summarize(
        read(args.baseline),
        read(args.current),
        read(root / "backend/app/domains/treatment/resources/planning-reference.json"),
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.markdown:
        Path(args.markdown).write_text(markdown(report), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False)
    )
