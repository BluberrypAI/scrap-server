# Agent Changelog

> 에이전트 문서(AGENTS.md, .agents/, docs/folder-architecture.md, docs/adr/)가 바뀔 때마다 기록함.
> 루프 엔지니어링의 기록장: 무엇을 겪었고(계기), 무엇을 바꿨는지(변경), 사용자가 승인했는지 남김.

| 날짜 | 계기 | 변경 내용 | 변경 파일 | 승인 |
| --- | --- | --- | --- | --- |
| 2026-10-15 | 초기 세팅 | 에이전트 7종, 스킬 6종, 작업 종료 루프 정의 | AGENTS.md, .agents/** | 사용자 승인 |
| 2026-10-15 | Git 전략·실행 방법·CI 도입 (사용자 요청) | 문서 지도에 git-workflow·backend README·runbooks 추가, 공통 규칙 7번(브랜치) 추가, 폴더 구조 갱신, ADR에 SQLite 지원 원칙 추가 | AGENTS.md, docs/folder-architecture.md, docs/adr/0001 | 사용자 요청으로 반영 |
| 2026-10-15 | 첫 마이그레이션에 SQLite 기본값 표현이 섞임, 로컬 PostgreSQL과 5432 포트 충돌 | db-migration 스킬에 server_default·alembic check 검토 항목과 5433 포트 안내 추가 | .agents/skills/db-migration/SKILL.md | 사용자 승인 |
| 2026-10-15 | 개발용 로그인 추가 | auth-specialist에 "토큰 응답 본문 금지"의 유일한 예외(dev-login) 명시 | .agents/agents/auth-specialist.md | 사용자 승인 |
| 2026-10-15 | 루트 README 추가 | 작업 종료 루프 점검표에 README(현재 구조·구현된 API)·backend/README·.env.example 갱신 조건 추가, 폴더 구조에 README 책임 추가 | AGENTS.md, .agents/skills/sync-agent-docs, docs/folder-architecture.md | 사용자 승인 |
| 2026-10-17 | 레포 4개 구성 확정(ADR 0002), 팀 전원 Docker 사용 | 이 레포를 server로 한정(MCP·근거 카드·infra 제외), 공통 규칙 8번(타 레포 API 형식 보호) 추가, team-conventions.md 신설·git-workflow는 server 적용분만 유지, 로컬 표준을 Docker PostgreSQL로 변경, db-engineer·evidence-card 범위 조정, todolist 레포별 재배치 | AGENTS.md, docs/adr/0001·0002, docs/folder-architecture.md, docs/git-workflow.md, docs/team-conventions.md, docs/todolist.md, .agents/agents/db-engineer.md, .agents/skills/evidence-card | 사용자 승인 |
| 2026-10-17 | ai 쪽 설계가 진행 중, 공개 레포에 기획서 원본 노출 우려 | evidence-card 스킬 삭제, 근거 카드·규칙표·지식그래프·RAG를 확정 설계처럼 적은 문구를 "ai 레포 지식 기반(설계 중)"으로 완화, ADR 0001에서 AI 구성 행 제거, 기획서 원본·research 폴더 삭제 및 .gitignore 추가, 기획서 링크를 product-plan 인용으로 대체 | AGENTS.md, README.md, docs/adr/0001·0002, docs/folder-architecture.md, docs/team-conventions.md, docs/todolist.md, docs/product-plan.md(링크만), .agents/agents/backend-architect·spec-writer·db-engineer, .agents/skills/write-spec, .agents/skills/evidence-card(삭제) | 사용자 요청 |
| 2026-10-17 | product-plan에 기획서 요약과 ai 쪽 설계가 남아 있음 | product-plan을 server 범위로 축소 (목적, 사용자, 포함·제외, 판단 원칙 4개, server 용어). 장 번호는 유지 | docs/product-plan.md | 사용자 요청 |
| 2026-10-17 | 영향이 없는 작업에서도 질문이 반복됨 | 작업 종료 루프를 "점검 결과는 항상 보고, 질문은 제안할 변경이 있을 때만"으로 변경. 직접 요청은 승인으로 간주. 스킬 예시를 server 기준으로 교체 | AGENTS.md 5장, CLAUDE.md, .agents/skills/sync-agent-docs | 사용자 승인 |
