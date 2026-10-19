# Todo List

> 상태값: `대기` `진행` `완료` `보류`. 작업을 시작·종료할 때 해당 에이전트가 갱신함 (형식은 update-todo 스킬).
> 일정 기준: 팀 기획서 9장 (기획서 원본은 레포 밖에서 관리)

## 1주차: 환경 세팅

| ID | 작업 | 상태 | 담당 | spec | 비고 |
| --- | --- | --- | --- | --- | --- |
| T-001 | 폴더 골격, uv 프로젝트, docker compose, Dockerfile | 완료 | backend-architect | - | |
| T-002 | users, social_accounts, companies, waste_profiles 모델과 첫 마이그레이션 | 완료 | db-engineer | auth-social-login, company-onboarding | Docker PostgreSQL·SQLite 양쪽에 적용 확인, upgrade/downgrade/check 통과 |
| T-003 | Google·Microsoft 소셜 로그인, JWT 쿠키, /users/me | 완료 | auth-specialist | auth-social-login | 실제 로그인은 T-007 이후 확인 |
| T-004 | 기업 온보딩 API (생성, 조회) | 완료 | api-developer | company-onboarding | |
| T-005 | 테스트 기본 구성 (OAuth mock) | 완료 | test-engineer | - | |
| T-006 | AGENTS.md, 에이전트 7종, 스킬 6종, 동기화 스크립트 | 완료 | backend-architect | - | |
| T-007 | Google OAuth 클라이언트, Entra ID 앱 등록 후 .env 설정 | 대기 | 사람 | auth-social-login | 리디렉션 URI는 spec 참고 |
| T-008 | 제공 Azure 자원 확인 (크레딧, 리전·SKU 제한, Azure OpenAI 할당량, 권한) | 대기 | 사람 | - | 배포 대상 결정의 선행 조건 |
| T-009 | 조사 문서 1~7 정리 | 보류 | 사람 | - | ai 레포·팀 문서 몫으로 이동 (이 레포에 올리지 않음) |
| T-010 | 기업 정보 수정 API (PATCH /companies/me) | 대기 | api-developer | company-onboarding | |
| T-011 | pre-commit 설정 (ruff, sync_agents --check) | 대기 | backend-architect | - | git init 이후 |
| T-012 | DB 설정 분리 (SQLite/PostgreSQL/Azure, SSL·풀), Docker 실행 구성, backend/README.md | 완료 | backend-architect | - | Docker DB 호스트 포트 5433 |
| T-013 | Swagger 설명·태그, DOCS_ENABLED | 완료 | api-developer | - | |
| T-014 | 이슈·PR 템플릿, CI, git-workflow.md | 완료 | backend-architect | - | |
| T-016 | 개발용 로그인 API (로컬 전용, Swagger 테스트용) | 완료 | auth-specialist | auth-social-login | |
| T-017 | 루트 README (소개, 실행 방법, 현재 구조, API 목록) | 완료 | backend-architect | - | |
| T-015 | GitHub 저장소 연결, 기본 브랜치·병합 방식·브랜치 보호 룰셋 설정 | 완료 | 사람 | - | 무료 플랜이라 룰셋은 강제되지 않음. 라벨은 쓰지 않음 |
| T-018 | 레포 4개 구성 반영 (ADR 0002), 팀 공통 규칙 문서, Docker 표준화 | 완료 | backend-architect | - | |
| T-019 | 조직 `.github` 레포 생성, CONTRIBUTING.md(=team-conventions) 등록 | 완료 | 사람 | - | Public. 템플릿은 `.github/` 하위 폴더 |
| T-021 | server 레포 `.github/ISSUE_TEMPLATE/` 삭제 (조직 템플릿으로 통일) | 취소 | 사람 | - | 조직 이슈 템플릿이 Private 레포에 적용되지 않아 레포별 템플릿으로 되돌림. PR 템플릿 간소화 |
| T-020 | ai·infra·frontend 레포 초기화, 템플릿, CI, 설정 | 완료 | 사람 | - | git-workflow.md 6장. CODEOWNERS는 두지 않음 |
| T-022 | Re_AI feat/#1 → develop PR에서 CI `test` 실행 확인 후 룰셋 status check에 추가 | 대기 | 사람 | - | AI 팀원 PR |
| T-023 | 로컬 폴더를 `resource-ai/` 아래 형제 구조(server, ai, frontend, infra, .github)로 정리 | 대기 | 사람 | - | git-workflow.md 6장 |

## 2주차 이후: server 레포 작업

| ID | 작업 | 상태 | 담당 | spec | 비고 |
| --- | --- | --- | --- | --- | --- |
| T-105 | server ↔ ai 연동 spec (분석 요청·결과 저장·보고서 조회 API, AI_BASE_URL) | 대기 | spec-writer | - | ai 팀과 형식 합의 필요 |
| T-106 | 분석(analyses) 도메인: 입력·문서 업로드 저장, ai 호출, 결과 저장 | 대기 | api-developer | - | T-105 이후 |
| T-502 | 배포 대상 결정 (App Service 기본안) 및 배포 | 대기 | 사람 | - | T-008 이후 |

## 참고: 다른 레포 담당 작업 (기획서 9장)

이 레포에서 구현하지 않음. 일정 파악과 연동 시점 확인용.

| 레포 | 주차 | 작업 |
| --- | --- | --- |
| ai | 2주 | parse_input, 지식 기반 구축 (설계 중), 정답셋 |
| ai | 3주 | find_pathways, map_value_loss, check_vendor |
| ai | 4주 | evaluate_options, assess_risk, 에이전트·MCP 연결 |
| ai | 5주 | draft_report, 정확도 평가 |
| frontend | 5주 | 단계별 3D 시각화, 결과 문서화 화면 |
| 전체 | 6주 | 시연 시나리오, 비교 시연, 발표 준비 |
