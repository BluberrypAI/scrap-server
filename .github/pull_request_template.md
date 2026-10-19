## 관련 항목

- 이슈: #
- todo: T-
- spec: docs/specs/

## 변경 내용

-

## 확인

- [ ] `uv run pytest` 통과
- [ ] `uv run ruff check .` / `uv run ruff format --check .` 통과
- [ ] 모델을 바꿨다면 마이그레이션을 추가하고 내용을 검토함
- [ ] docs/todolist.md 상태 갱신

## 작업 종료 루프 (AGENTS.md 5장)

- [ ] 문서 영향 점검함: folder-architecture / ADR / spec / .agents
- 점검 결과: <!-- 영향 없음, 또는 갱신한 문서와 이유 -->
- [ ] .agents/를 바꿨다면 `scripts/sync_agents.py`로 동기화하고 docs/agent-changelog.md에 기록함
