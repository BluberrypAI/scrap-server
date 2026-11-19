"""Sync tool-neutral agent docs (.agents/) into Claude Code's locations (.claude/).

    python scripts/sync_agents.py          # write .claude/agents and .claude/skills
    python scripts/sync_agents.py --check  # exit 1 if .claude/ is out of date

.agents/ is the source of truth. Codex reads .agents/skills directly; Claude Code
reads .claude/agents and .claude/skills, which this script generates.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".agents"
DST = ROOT / ".claude"
TARGETS = ("agents", "skills")

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
NOTICE = "<!-- 생성물: {source} 를 수정하고 scripts/sync_agents.py 로 동기화하세요 -->\n"


def parse_frontmatter(text: str) -> dict[str, str] | None:
    match = FRONTMATTER.match(text)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def validate(path: Path, expected_name: str) -> list[str]:
    fields = parse_frontmatter(path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT).as_posix()
    if fields is None:
        return [f"{rel}: frontmatter(---)가 없음"]
    errors = [f"{rel}: '{key}' 항목이 없음" for key in ("name", "description") if not fields.get(key)]
    if fields.get("name") and fields["name"] != expected_name:
        errors.append(f"{rel}: name '{fields['name']}'이 파일·폴더 이름 '{expected_name}'과 다름")
    return errors


def with_notice(path: Path) -> bytes:
    """Insert a do-not-edit notice right after the frontmatter of markdown files."""
    if path.suffix != ".md":
        return path.read_bytes()
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    notice = NOTICE.format(source=path.relative_to(ROOT).as_posix())
    if not match:
        return (notice + text).encode("utf-8")
    return (text[: match.end()] + notice + text[match.end() :]).encode("utf-8")


def expected_files() -> tuple[dict[Path, bytes], list[str]]:
    files: dict[Path, bytes] = {}
    errors: list[str] = []

    for path in sorted((SRC / "agents").glob("*.md")):
        errors += validate(path, path.stem)
        files[DST / "agents" / path.name] = with_notice(path)

    for skill_dir in sorted(p for p in (SRC / "skills").glob("*") if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            errors.append(f"{skill_dir.relative_to(ROOT).as_posix()}: SKILL.md가 없음")
            continue
        errors += validate(skill_md, skill_dir.name)
        for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
            files[DST / "skills" / path.relative_to(SRC / "skills")] = with_notice(path)

    return files, errors


def existing_files() -> set[Path]:
    return {p for target in TARGETS for p in (DST / target).rglob("*") if p.is_file()}


def file_matches(path: Path, expected: bytes) -> bool:
    if not path.exists():
        return False
    actual = path.read_bytes()
    # Git autocrlf changes Markdown line endings on Windows, not its content.
    if path.suffix == ".md":
        actual = actual.replace(b"\r\n", b"\n")
        expected = expected.replace(b"\r\n", b"\n")
    return actual == expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="수정하지 않고 동기화 여부만 검사")
    args = parser.parse_args()

    files, errors = expected_files()
    if errors:
        print("검증 실패:", *errors, sep="\n  ")
        return 1

    stale = existing_files() - files.keys()
    changed = [p for p, content in files.items() if not file_matches(p, content)]

    if args.check:
        if stale or changed:
            for p in sorted(changed):
                print(f"  변경 필요: {p.relative_to(ROOT).as_posix()}")
            for p in sorted(stale):
                print(f"  삭제 필요: {p.relative_to(ROOT).as_posix()}")
            print("동기화되지 않음: python scripts/sync_agents.py 를 실행하세요")
            return 1
        print("동기화 상태 정상")
        return 0

    for p in changed:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(files[p])
    for p in stale:
        p.unlink()
    for target in TARGETS:
        for d in sorted((DST / target).rglob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                shutil.rmtree(d)

    print(f"동기화 완료: 변경 {len(changed)}개, 삭제 {len(stale)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
