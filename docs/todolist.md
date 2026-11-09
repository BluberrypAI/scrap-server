# Todo List

> 상태값: `대기` `진행` `완료` `보류`. 작업을 시작·종료할 때 해당 에이전트가 갱신함 (형식은 update-todo 스킬).
> 일정 기준: 팀 기획서 9장 (기획서 원본은 레포 밖에서 관리)

## 1주차: 환경 세팅

| ID | 작업 | 상태 | 담당 | spec | 비고 |
| --- | --- | --- | --- | --- | --- |
| T-001 | 폴더 골격, uv 프로젝트, docker compose, Dockerfile | 완료 | backend-architect | - | |
| T-002 | users, social_accounts, companies, waste_profiles 모델과 첫 마이그레이션 | 완료 | db-engineer | auth-social-login, company-onboarding | Docker PostgreSQL·SQLite 양쪽에 적용 확인, upgrade/downgrade/check 통과 |
| T-003 | Google·Microsoft 소셜 로그인, JWT 쿠키, /users/me | 완료 | auth-specialist | auth-social-login | 로컬에서 Google·Microsoft 실제 로그인 확인 (2026-10-22) |
| T-004 | 기업 온보딩 API (생성, 조회) | 완료 | api-developer | company-onboarding | |
| T-005 | 테스트 기본 구성 (OAuth mock) | 완료 | test-engineer | - | |
| T-006 | AGENTS.md, 에이전트 7종, 스킬 6종, 동기화 스크립트 | 완료 | backend-architect | - | |
| T-007 | Google OAuth 클라이언트, Entra ID 앱 등록 후 .env 설정 | 완료 | 사람 | auth-social-login | 로컬(localhost:8000)용 등록 완료. 배포 시 리디렉션 URI 추가 필요 |
| T-008 | 제공 Azure 자원 확인 (크레딧, 리전·SKU 제한, Azure OpenAI 할당량, 권한) | 대기 | 사람 | - | 배포 대상 결정의 선행 조건 |
| T-009 | 조사 문서 1~7 정리 | 보류 | 사람 | - | ai 레포·팀 문서 몫으로 이동 (이 레포에 올리지 않음) |
| T-010 | 기업 정보 수정 API (PATCH /companies/me), 필드를 API 명세(CORP-002)에 맞춤 | 완료 | api-developer | company-onboarding | 경로는 /companies/me 유지 (사용자 결정) |
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
| T-105 | server ↔ ai 연동 spec (분석 요청·결과 저장·보고서 조회 API, AI_BASE_URL) | 완료 | spec-writer | review-runs | ai develop의 /analysis/research 계약 기준. 보고서는 post-MVP |
| T-106 | 분석(analyses) 도메인: 입력·문서 업로드 저장, ai 호출, 결과 저장 | 완료 | api-developer | review-intake, review-documents, review-runs | reviews·documents·runs 도메인으로 나눠 구현 (T-112~T-114) |
| T-107 | refresh 토큰 DB 기록·회전·폐기, 로그아웃 서버 무효화, /users/me 응답 정리(provider, company_id) | 완료 | auth-specialist | auth-social-login | has_company 제거 (사용자 결정) |
| T-108 | 회원 탈퇴 (POST /users/me/withdraw, 30일 유예 후 삭제, purge 명령) | 완료 | auth-specialist | account-withdrawal | product-plan 3장에 탈퇴 추가 필요 (사람) |
| T-109 | 공통 오류 응답 형식 (code, message, details), 기존 API 전체 적용 | 완료 | api-developer | error-response | API 명세표의 오류 코드와 맞춤 |
| T-110 | 탈퇴 사용자 purge 스케줄 (하루 1회) | 대기 | 사람 | account-withdrawal | 배포 대상 결정(T-502) 이후 |
| T-111 | 기업 정보 변경 이력 조회 (GET /companies/me/history, 페이지네이션) | 완료 | api-developer | company-onboarding | CORP-006 |
| T-112 | 검토 생성·조회와 입력 정리 (reviews, intake) | 완료 | api-developer | review-intake | 이슈 #17. API 명세 v3 API-019~022, 046 |
| T-113 | 문서 업로드와 측정값 검수 (documents, values) | 완료 | api-developer | review-documents | 이슈 #18. 값 추출(OCR)은 INT-008 결정 후 |
| T-114 | 검토 실행과 AI 엔진 연동 (runs, 워커, 오류 분류) | 완료 | api-developer | review-runs | 이슈 #19. 워커는 프로세스 내 실행 |
| T-115 | 검토 결과 조회 (후보 목록·상세, 검토 대기, 확인 과제, 버전 비교) | 완료 | api-developer | review-results | 이슈 #20 |
| T-116 | 리스크 단계 결정, 추가 자료, 재실행 | 완료 | api-developer | review-risks-supplements | 이슈 #21. 재실행은 항상 research부터 (INT-005 기능 축소) |
| T-120 | AI 없이 백엔드를 검증하는 가짜 엔진 모드와 계약 스냅샷 | 완료 | api-developer | dev-mock-engine | 이슈 #27. AI_ENGINE_MODE=mock, 스냅샷은 ai 스키마 변경 시 수동 갱신 |
| T-121 | 인계 QR의 인수·입고 이벤트 서버 저장 | 완료 | api-developer | transport-handoffs | 로컬 PostgreSQL과 별도 브라우저 시연 확인 |
| T-122 | 전국 처리업체 명부·다음 공정 API를 서버 PostgreSQL에 연결 | 완료 | db-engineer | treatment-registry | 전국 원본 9,604행 적재. PP·폐금속 번호 조회의 조인 오류 수정 및 웹에서 재검증 |
| T-123 | PP 문진의 R코드를 공정별 조사에 연결 | 완료 | api-developer | treatment-registry | 화성 A의 사출 잔재·파쇄품을 웹에서 비교. 추가 공개 조사 결과는 인계 보류 |
| T-124 | 첫 공정의 업체 후보 전체를 Astra로 자동 검토 | 완료 | api-developer | treatment-registry | 화성 A의 PP 사출 잔재 3곳과 파쇄품 2곳에 대해 웹에서 Astra 실제 응답 확인 |
| T-125 | 실제 산출물 기준 후속 업체 후보 전체를 Astra로 자동 검토 | 완료 | api-developer | treatment-registry | B의 PP 파쇄품으로 C 후보 2곳 실검토 및 A·B·C QR 추적 종료 확인 |
| T-126 | 예정 산출물과 실제 처리 결과를 구분해 추적 | 완료 | api-developer | treatment-registry | A·B 예정 후보 공유, 미확인 기록, 형태 한 번 확인, 측정값 보충, Astra·QR 연동을 웹에서 확인 |
| T-127 | 신규 로트 문진 유형과 첫 업체 조회 범위 제한 | 완료 | api-developer | treatment-registry | 서버에서 유형과 분류 세션을 검증하고 R코드 전달 |
| T-128 | DB 스키마 간소화: 검토·실행·문서·결과·리스크·보완 자료 기능 삭제, social_accounts를 users에·waste_profiles를 companies에 합침, 온보딩 입력을 프론트 화면에 맞춤, treatment_facility_listings → facility_import_rows | 완료 | db-engineer | db-schema-simplify | SQLite에서 마이그레이션 upgrade/downgrade/check 확인. PostgreSQL은 CI에서 확인 |
| T-129 | 프론트 연동 기반: 본문을 읽지 못한 400의 오류 코드를 VALIDATION_ERROR로, 프론트 프록시로 실행하는 방법 문서화 | 완료 | api-developer | error-response | 프론트 Vite 프록시로 로그인·기업 API 호출 확인 |
| T-118 | 검토 실행을 Service Bus + 별도 워커 파드로 이전 | 대기 | backend-architect | review-runs | 요구사항 NFR-6, infra 리소스 확정 후 |
| T-119 | server ↔ ai 서비스 간 인증 (Entra ID) | 대기 | auth-specialist | review-runs | 요구사항 NFR-1, ai 팀 합의 필요 |
| T-117 | 문서 값 추출 방식 결정 (Azure Document Intelligence / 다른 벤더 / 수동 입력) | 대기 | 사람 | review-documents | 엔진 연동 INT-008 |
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
