---
name: sync-agent-docs
description: 작업을 마칠 때마다 사용. 이번 작업이 AGENTS.md, .agents/, folder-architecture, ADR, spec에 영향을 주는지 점검하고, 결과를 보고하고, 제안할 변경이 있으면 사용자에게 묻고, 승인되면 반영·기록·동기화함.
---
<!-- 생성물: .agents/skills/sync-agent-docs/SKILL.md 를 수정하고 scripts/sync_agents.py 로 동기화하세요 -->

# sync-agent-docs (작업 종료 루프)

AGENTS.md 5장의 상세 절차. **모든 작업 끝에 수행함. 점검 결과 보고는 생략하지 않고, 질문은 제안할 변경이 있을 때만 함.**

## 1. 변경 수집

이번 작업에서 만들거나 고친 파일, 내린 결정, 겪은 문제를 목록으로 정리함. git을 쓰면 `git status`, `git diff --stat`으로 확인함.

## 2. 영향 판단

| 신호 | 갱신 대상 | 예시 |
| --- | --- | --- |
| 새 폴더·도메인, 파일 위치 규칙 변경 | docs/folder-architecture.md, README.md(현재 구조) | domains/analyses 추가 |
| API 추가·변경, 실행 방법·환경변수 변경 | README.md(구현된 API), backend/README.md, .env.example | PATCH /companies/me 추가 |
| 기술·라이브러리·구조 결정 | docs/adr/NNNN-*.md (새 파일) | Redis 도입, 그래프 DB 전환 |
| 구현이 spec과 다름, spec에 없는 결정 | docs/specs/*.md | 상태 코드 변경, 필드 추가 |
| 같은 절차를 2번 이상 반복 | .agents/skills/ 새 스킬 | 매번 같은 순서로 도메인 추가 |
| 에이전트가 같은 실수를 반복, 스킬 지침이 부족 | .agents/skills/ 기존 스킬 보완 | 마이그레이션 검토 누락 |
| 역할 경계가 모호, 새 역할 필요 | .agents/agents/, AGENTS.md 3장 | 분석 연동 전담 역할 추가 |
| 공통 규칙 부족으로 잘못된 방향 작업 | AGENTS.md 2장 | 금지 사항 추가 |

해당 없음도 결과임. 억지로 변경을 만들지 않음.

## 3. 보고와 질문

제안할 변경이 **없으면** 한 줄만 보고하고 질문하지 않음:

```
문서 영향 점검: 영향 없음
```

제안할 변경이 **있으면** 질문함:

```
[에이전트 문서 업데이트 확인]
- 점검 결과: <영향 있는 문서와 이유>
- 제안 변경:
  - <파일>: <한 줄 요약>
에이전트 문서를 업데이트할까요?
```

- 승인 전에는 대상 문서를 수정하지 않음
- 서브에이전트는 이 질문을 최종 보고에 담고, 메인 에이전트가 사용자에게 물음
- 사용자가 일부만 승인하면 승인한 것만 반영함
- 사용자가 작업 지시와 함께 문서 변경을 직접 요청했으면 그 요청을 승인으로 봄

## 4. 반영 (승인 후)

1. 대상 문서 수정. 문서는 짧게 유지하고, 중복 규칙은 한 곳에만 둠
2. docs/agent-changelog.md에 한 줄 추가: `| 날짜 | 계기 | 변경 내용 | 변경 파일 | 승인 |`
3. `.agents/`를 바꿨으면 동기화:
   ```bash
   cd backend && uv run python ../scripts/sync_agents.py
   ```
4. `uv run python ../scripts/sync_agents.py --check`로 동기화 상태를 확인함
