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
| T-131 | ERD v2 반영: wastes, route_steps, qr_field_checks, waste_completion_snapshots, facilities, facility_waste_codes, facility_r_types 추가, companies 좌표·main_products 기본값 | 완료 | db-engineer | erd-v2-alignment | SQLite·PostgreSQL에서 마이그레이션 upgrade/downgrade/check와 테스트 확인. 배출 통계는 보류 |
| T-130 | 문진 엔진(scrap-diagnosis) 연동: /api/v1/diagnosis/* 중계, 엔진 오류 변환, 탈퇴 purge 엔진 삭제, compose engine 프로필 | 완료 | api-developer | diagnosis-engine-integration | 엔진 develop(LLM off, 토큰 사용)과 실제 연결해 건 생성~확정·reopen·서류 값 오류 확인. Azure LLM 자유 진술은 미확인 |
| T-132 | 확정 문진 → 첫 공정·업체 전체 AI 검토 연결 | 완료 | api-developer | diagnosis-treatment-bridge | PP 웹/DB/Azure 실호출 확인. R코드·PET/금속·QR 연계는 후속 작업 |
| T-133 | PP 상태·사진 공유, 수신 기업 수락, QR 입고, 실제 산출물 기반 다음 인계·완료 | 완료 | 구현 | pp-company-workflow | 별도 가상 기업 계정으로 A→B 및 A→B→C 웹 완료. PostgreSQL·Azure 실호출. 파일 선택기·실물 QR·실제 업체 허가는 미검증. 검증 기록: pp-company-e2e.md |
| T-134 | 현재 상태 설명·사진을 후보 전체 Astra 검토에 반영 | 완료 | 구현 | pp-company-workflow | A→B 3곳, B→C 2곳(사진 없음/새 사진) Azure 실제 호출. 관찰·진술·미확인 분리, 수락은 업체 결정. 서버 166개·신규 PostgreSQL 9개 통과 |
| T-135 | 사진 전용 관찰과 업체 대조 분리 결과 연동·구버전 검토 차단 | 완료 | api-developer | pp-company-workflow | 기존 웹 계약 유지, 관찰 방식·확인사항 유형 추가. 서버 168개·PostgreSQL 기업 인계 11개 통과. 사진으로 반입 승인하지 않음 |
| T-137 | 기업 인계 테이블 마이그레이션의 시각 기본값을 SQLite에서도 동작하게 수정 | 완료 | db-engineer | pp-company-workflow | now() 문자열 → sa.func.now(). 마이그레이션으로 만든 SQLite DB 회귀 테스트 추가. PostgreSQL 스키마는 동일 |
| T-138 | 기업 인계 API 오류를 공통 형식으로 반환 (이유 문구가 "요청 처리 실패"로 바뀌던 문제) | 완료 | api-developer | error-response | HTTPException → AppError, FORBIDDEN·WORKFLOW_CONFLICT 추가. 오류 형식 테스트 2개 추가 |
| T-136 | 로컬 시험용 업체 계정 연결 스크립트(dev_accounts) | 완료 | api-developer | pp-company-workflow | APP_ENV=local·test 전용. 개발 로그인 기업을 PP 업체 키에 synthetic으로 연결 |
| T-139 | 기업 인계를 PE 필름·알루미늄캔으로 확장 (문진·처리경로 교집합) | 완료 | api-developer | pp-company-workflow | 재질별 시작 상태·완료 산출물, 산출물 상태 재질 검사, dev_accounts 알루미늄 연결. 테스트 추가(서버 177개 통과). 당시 PET병은 제외했으나 현재 두 PET 번호 연결은 T-154에서 재검증. 실제 반입 승인과는 별개 |
| T-140 | 업체별 질문·전국 명부 조회·조건부 수락 연결 | 완료 | api-developer | intake-conditions-local | 후보 답변→AI 재검토, 조건별 자료→수신 확인→QR. 공개 프로필 7곳, 시설 15곳/연결 29개. 서버 188개 통과, 웹 조건부 인계 검증 |
| T-142 | 플라스틱별 공개 사업장·다음 공정 확장 | 완료 | api-developer | plastic-facility-expansion | 37곳·81개 연결. 원본 전수 선별 4,359행, 재활용업 1,935묶음. 48개 조합 중 45개 조사 후보·3개 보류. 서버/PostgreSQL 각각 259개 통과. 소재별 실제 반입·허가는 미확인. [범위와 검증](plastic-facility-expansion.md) |
| T-141 | 실제 업체 반입규격·수신계정 인증 | 대기 | 사람 | intake-conditions-local | PET 두 번호 연결·폐PET병 형태 검사는 T-154에서 수정/재검증. 수분·오염·물량 한도/현행 허가/여유 용량과 실제 수신 기업 인증은 미확보. 역할 추정 11개는 별도 확인 필요. 코드 연결 완료와 실제 반입 승인을 구분 |
| T-143 | 플라스틱 조사 대기열의 사업장별 공정·반입 형태 추가 대조 | 완료 | api-developer | plastic-facility-expansion | 47곳·102연결. 공장등록 220,705행 대조→이름/주소 일치 323묶음(조사 단서). 신규 10곳, 역할 5개 보강/14개 유지. SQLite·PostgreSQL 297개씩, 로컬 조회 48개, Azure 12개. [검증](plastic-facility-expansion.md) |
| T-144 | 남은 사업장별 반입 형태·공정 근거 확보 | 대기 | api-developer | plastic-facility-expansion | 전수 대조 323묶음 중 미검토 공정, 주소 미해결 582묶음, CNTK 12/BGF 화성 2, 국내 PE·PS 베일 수령 근거 추가. 원료/설비와 제품판매 구분. [보류 단서](registry-screen/held-leads.md) |
| T-145 | 문진 확정→경로 연결의 플라스틱 전 조합 회귀 검증 | 완료 | test-engineer | diagnosis-treatment-bridge | 48개 조합의 형태 선택·번호 보존·후보/보류 응답 확인. PET 51-03-01 미지원 화면의 배포 버전·handoff 대조는 별도 필요. 웹의 빈 결과 안내도 보강 |
| T-146 | 기업 좌표 입력·변경 이력·현재 보유 기업 기준 Top 5 연결 | 완료 | api-developer | company-onboarding | 좌표 쌍 검증, 주소 변경 시 초기화, AI 캐시 버전 및 호출 중 변경 검사. 브라우저 저장·재조회 확인. 직선거리이며 좌표 미확인 업체는 별도 표시 |
| T-147 | 문진 고체 정보 누락 시 사용자 확인으로 경로 연결 | 완료 | api-developer | missing-solid-confirmation | 알루미늄 음료캔 문진에 고체 질문이 없어 막힌 문제 수정. 액체 결과를 덮어쓰지 않음. 실제 Azure·별도 계정 QR 완료 확인 |
| T-148 | 최신 5레포와 전체 활성 공정 연결 통합 검증 | 완료 | test-engineer | diagnosis-treatment-bridge | 176개 HTTP 조회로 97/102 연결 도달(5개는 범위 밖 종이), Azure 97개 전부 검토. PP·PET·PE 각 직접/중간 인계 및 캔 7건 완료. server SQLite·PostgreSQL 각 356 통과. [결과](full-stack-validation-20261115.md) |
| T-149 | 미지원 금속 공정·베일 반입·사업장 좌표 추가 확인 | 진행 | api-developer | plastic-facility-expansion | 철스크랩 2곳 연결(T-150). 일반 비철은 재질 특정 필요. EPS 감용 1곳 추가(T-151). PE·PS 베일 수령 사업장과 좌표 근거 부족은 유지. 실제 업체 수락은 별도. 도로 거리 API는 키·연동 검증 필요 |
| T-150 | 현재 상태의 모든 등록 공정 조회·업체 없는 공정 표시·공개 조사 확장 | 완료 | api-developer | next-process-coverage | HTTP 197회로 지원 공정 53개·연결 99개 도달. 최종 경로·미리보기 예산과 직접 후보 분리. 철스크랩 2곳/EPS 감용 공정 추가. SQLite 413, route 512, web 47 통과. [범위·근거](route-coverage-20261115.md) |
| T-151 | EPS 감용 사업장 연결·베일 수령 근거 추가 대조 | 완료 | api-developer | plastic-facility-expansion | 50곳·105연결. EPS 감용물/인고트 분리, SQLite 415, HTTP 198회, 신규 Azure 1건 확인. PE·PS 베일은 실제 수행 사업장 부족으로 보류. [근거](registry-screen/bale-eps-review-20261115.md) |
| T-152 | 실제 문진 18선택지→번호→형태 32개→업체·AI 연결 전수 검사 | 완료 | test-engineer | diagnosis-treatment-bridge | 일반 12번호. 9선택지·30형태 후보 연결, 9선택지 미지원·2베일 보류. Azure 174건 중 근거 확인 23/부족 151. web 지도 worker 수정·재검사. [결과](classification-route-e2e-20261115.md) |
| T-153 | 포장재·어망·기타 수지·비철의 세부 재질 보충과 물량 전달 | 완료 | api-developer | material-detail-bridge | 원래 번호 보존, 8개 세부 재질 선택·AI·로트 저장 연결. 실제 18문진/52형태 중 49조합 후보, 신규 20형태 브라우저 확인. 서버 SQLite·PG 439개씩. [결과](material-detail-e2e-20261115.md) |
| T-154 | AI 공개 근거 부족과 호출 장애의 원인별 보강 | 완료 | api-developer | evidence-gap-audit | 부족 사유 9종·PET병 인용 검사·제한된 재시도·프록시 대기 보강. 기존 252회(35사업장·79연결) 재검토: 확인 10/부족 242. 전체 53형태·294검토: 확인 50/부족 244/최종 호출 오류 0. 59브라우저 검사 통과. 근거 부족이 전부 해소됐다는 뜻은 아님. [사유별 결과](registry-screen/intake-evidence-gaps-20261116.md) |
| T-118 | 검토 실행을 Service Bus + 별도 워커 파드로 이전 | 대기 | backend-architect | review-runs | 요구사항 NFR-6, infra 리소스 확정 후 |
| T-155 | diagnosis의 R유형·분석 조건을 UI·물량·AI에 전달 | 완료 | api-developer | recycling-handoff | 일반 14번호의 법령표·분석 조건·출처 연결, 이전 확정 건 보충 조회·검토 캐시 갱신. 새 문진 18건·웹 59검사·위험성 11건·Azure 53조합/294후보 결과와 실제 물량 등록/재접속 확인. 최초 호출 장애 2조합 재시도. [검증 결과](r-code-flow-audit-20261116.md) |
| T-156 | 공개 근거 검토의 과도한 보류·잘못된 통과를 독립 정답셋으로 평가 | 진행 | test-engineer | recycling-handoff | 넷스파 PA6 어망·대한제강 녹산 철스크랩 원문을 추가 대조하고 실제 Azure에서 공개 근거 확인 응답. 다른 재질·사업장·반입 제한 음성 테스트 추가. 독립 전문가 정답셋 및 반복 판정 편차 평가는 미완료이며 실제 반입 허가 확인과 별개 |
| T-157 | 수도권 공정·업체 근거 보강 및 문진·후속 산출물 연결 검사 | 완료 | api-developer | capital-region-coverage | 9사업장·19연결 추가, 경기22/인천5 연결 사업장. 18문진·59웹·212HTTP, 신규19연결 포함 Azure67검토. 신규 근거 확인7/부족12, 일반 PE·PS 베일·PU/고무/페놀 미지원 유지. [범위·남은 일](capital-region-coverage-20261116.md) |
| T-158 | 추가 근거 12개·PE/PS 베일 재조사 및 수도권 후보 후속 검증 | 완료 | api-developer | intake-evidence-followup | 화성 LDPE 필름 1사업장·1연결, 원문5개 추가. 기존12중1개 근거 확인·11개 보류. 18문진·59웹·212HTTP, Azure142응답/124고유 연결. 일반 PE·PS 베일 반입 근거 확보는 T-149에서 계속. [결과·한계](intake-evidence-followup-validation-20261116.md) |
| T-159 | 최신 UI 로그인부터 PP A→B / A→B→C 완료 재검사 | 진행 | test-engineer | e2e-release-20261117 | 개발용 별도 기업 계정으로 문진·사진·전체 후보 Azure 검토·조건부 수락·자료 제출·QR 2회·완료·A 이력까지 웹 통과. UI 상태 갱신·문진 초기 성능·서버 대기 설정 수정. Google/Microsoft OAuth는 인증정보 미설정으로 미검증. [검증 범위와 남은 조건](full-login-e2e-20261117.md) |
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
