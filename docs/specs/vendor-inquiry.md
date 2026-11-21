# 후보 업체 문의서와 최신 검토 확인

상태: 2026-11-17 사용자 고도화 요청에 따른 구현 범위.

가입하지 않은 후보에서 흐름이 끊기지 않도록, 현재 물량과 업체별 확인 질문을 사람이 보낼 수 있는 문의서로 준비한다. 자동 발송·실제 업체 연락·허가 인증·계정 연결은 하지 않는다.

- POST /api/v1/workflow/lots/{id}/inquiry-packet. 요청은 revision, capability_key. 응답은 version, generated_at, filename, text. 현재 물량 보유 기업만 가능.
- 현재 단계 후보만 선택할 수 있다. 사진/답변/산출물 변경으로 무효화된 검토, 사업장 프로필·공정/반입자료·도로 서비스 버전이 바뀐 검토는 409로 재검토를 안내한다. 같은 최신 검토 확인을 실제 인수 요청에도 적용한다.
- 문의서에는 발송 기업/사업장, 대상 업체/주소, 현재 형태·중량·상태 설명, 공정, AI 검토/미확인점, 후보별 답변과 미응답 질문, 근거 링크·확인일을 담는다. B 단계는 최초 분류와 현재 산출물을 구별하고 최초 R유형을 현재 인계에 적용하지 않는다.
- 추가 확인할 최소 물량·포장·일정·견적·허가 범위는 질문으로 남기고 추정값을 채우지 않는다. AI 실패·반입 제한은 문서에 그대로 표시한다. 문서 생성은 인수 승인/계약이 아니며 QR/offer/진행 상태를 바꾸지 않는다.
- 개인정보 최소화: 계정 이메일·사용자 ID·원시 사진·사진 접근 URL·QR 토큰·과거 기업 정보는 포함하지 않는다. 현재 기업명/사업장 주소와 물량 설명이 포함됨을 다운로드 전 알린다.
- 웹에서 미리보기·텍스트 복사·UTF-8 텍스트 저장. 자동 외부 전송 없음. 저장된 파일은 사용자가 관리한다. 서버에 추가 파일/DB 기록은 생성하지 않으며 응답은 no-store.

검증: 타 기업 접근 차단, 과거 보유자 차단, 후보 바꿔치기·오래된 revision 차단, 사업장 변경 후 문의/인수요청 차단, AI 실패/제한 표시, B 산출물·최초 코드 구분, 사진/토큰 노출 없음, 문의 생성 후 로트·인계 불변, 실제 웹 미리보기와 저장 확인.

## 메일 제목과 업체 답장 등록 (2026-11-20)

메일 자동 발송·수신은 없다. 고객이 문의서를 자기 메일 앱으로 보내고, 받은 답장 내용·첨부파일을 해당 문의(물량 + 후보 capability_key)에 직접 등록한다.

- inquiry-packet 응답에 `subject`(메일 제목, 120자 이내, 한 줄) 추가.
- GET/POST /api/v1/workflow/lots/{id}/inquiries/{capability_key}/replies. POST는 multipart(text 5000자 이하, received_on YYYY-MM-DD 미래 불가, file). text·file 중 하나 필수, 문의당 50건. 현재 업체 검토 결과에 있는 후보만, 진행 중(ready/processed) 물량에서만 등록. 조회는 등록한 기업 본인 것만.
- 파일: 10MB 이하, PDF·JPEG·PNG·WebP·XLSX·DOCX·HWP·HWPX, 확장자와 앞부분 서명이 맞아야 하며 mime은 서버가 정함.
- GET /api/v1/workflow/inquiry-replies/{id}/file (attachment, nosniff, no-store), DELETE /api/v1/workflow/inquiry-replies/{id} (204). 등록한 기업만.

## 2단계 — 링크로 답하기 (2026-11-21 확정)

- 현재 물량 보유 기업이 `/api/v1/workflow/lots/{lot_id}/inquiries/{capability_key}/reply-link`에서 링크를 관리한다. POST(201)는 `status: active`, `token`, `path: /#/reply/{token}`, `expires_at`을 반환하며 이전 링크를 즉시 무효화한다. GET(200)은 `status: none|active|expired|revoked`, `expires_at`만 반환하고 DELETE(204)는 링크를 중지한다. 토큰은 32바이트 난수로 만들고 SHA-256 해시만 저장한다. 유효 기간은 14일이다.
- `/api/v1/public/inquiry-replies/{token}`은 로그인 없이 접근한다. GET은 `sender_company_name`, `facility_label`, `subject`, `inquiry_text`, `expires_at`, `reply_count`, `max_replies`(10)를 반환한다. 발급 시 기존 문의서 생성 로직을 재사용하며 사진, 다른 후보, 내부 ID, 고객 담당자 개인정보는 제공하지 않는다.
- 공개 POST는 multipart로 `availability`(필수, `available|conditional|unavailable`), `text`(2,000자), `contact_name`(100자), `contact_info`(200자), `file`(1단계 파일 규칙)을 받고 201과 `id`, `created_at`을 반환한다. 미등록·만료·중지·진행 상태 변경 또는 후보 제외 시 같은 404를 반환한다. 입력 오류는 422, 토큰·IP별 분당 10회 또는 링크당 누적 10건 초과는 429(`RATE_LIMITED`)다. 공개 응답에는 `Cache-Control: no-store`, `X-Robots-Tag: noindex`를 설정한다.
- 답장 목록에 `source`(`sender|vendor_link`), `availability`, `contact_name`, `contact_info`를 추가한다. 기존 행은 `sender`다. 업체 답장은 고객이 기존 API에서 내려받거나 삭제할 수 있다. 업체가 추가 답장으로 정정할 수 있으며 삭제한 답장도 링크의 누적 건수에 포함한다. 메일 자동 전송과 인수 수락 처리는 없다.
- (v2, 2026-11-21) inquiry-packet 응답에 업체에 보낼 짧은 메일 본문 `mail_body`(링크 미포함, 900자 이내)를 추가한다. 인사·물량 정보(품목, 중량, 상태, 참고 분류번호, 시·군·구까지의 출발지와 도로거리, 희망 처리)·여쭙는 내용 3가지·서명으로 구성하고 AI 검토, UTC 시각, URL, 내부 ID는 넣지 않는다. 공개 GET 응답에는 링크 발급 시점의 `summary`(item, weight_kg, condition, waste_code, origin_region, road_distance_km, process, questions)를 더하며, summary가 없던 이전 링크는 `summary: null`이다. 기존 `inquiry_text`는 상세 문의서로 유지한다.

## 링크 참여 임시 계정 (v3, 2026-11-21 확정)

- 공개 `POST /api/v1/public/inquiry-replies/{token}/join`은 유효한 링크의 임시 계정으로 로그인 쿠키를 발급하고 `200 {"company_name": string, "lot_visible": boolean}`을 반환한다. `lot_visible`은 해당 계정에 인수 요청이 있어 처리 건을 볼 수 있다는 뜻이다. 미등록·만료·중지 링크는 기존 공통 404, 업체에 정식·시연 계정이 연결돼 있으면 409 `ALREADY_CONNECTED`다. GET·공개 답장·join은 IP와 토큰별 제한을 공유한다.
- 공개 GET의 `joinable`은 해당 링크로 로그인할 수 있는지, `joined`는 임시 계정이 생성됐는지를 나타낸다. 해당 임시 계정에 인수 요청이 생기면 진행 상태가 바뀌어도 유효 기간 안에 공개 GET과 join을 사용할 수 있다. 공개 답장은 기존 접수 조건을 따른다. 발급자는 임시 계정에 이미 인수 요청을 보냈으면 이전 문의 내용으로 링크를 재발급하거나 중지할 수 있다.
- 사용자(provider `reply-link`, subject는 링크 행 ID)와 기업은 `lot_id`·`capability_key`당 하나이며 재발급 때 재사용한다. 기업 이름은 `{업체명} (링크 참여)`이고 주소·좌표는 공개 후보 자료에서 가져온다. 사용자의 이메일은 null, 회사의 연락 이메일과 미확인 주소는 빈 문자열이다. 업체 전체에 적용되는 수신 계정 연결은 생성하지 않는다.
- `/api/v1/users/me`와 `/api/v1/companies/me`에 `guest`를 추가한다. 임시 계정은 회사 정보 수정과 회원 탈퇴에 403을 받는다. 링크 중지는 임시 계정의 모든 refresh 세션과 해당 세션의 access 쿠키를 무효화한다. 링크 만료는 새 링크 로그인을 차단하며 이미 발급된 세션은 기존 세션 만료 규칙을 따른다. 인수 요청과 입고 기록은 보존한다.
- 현재 후보의 `recipient`는 기존 연결을 우선하며 `guest: false`를 추가한다. 기존 연결이 없으면 현재 물량·후보에 대응하는 유효한 링크로 참여한 회사만 `synthetic: false, guest: true`로 표시한다. 기존 인수·대화·QR·입고·결과 API의 권한과 입력을 적용하며, 입고 뒤 공개 사업장 좌표로 다음 공정의 도로거리 조회를 할 수 있다. 링크 참여는 업체 확인이나 허가 확인을 의미하지 않는다.

완료 조건은 쿠키 로그인, 재참여·재발급 시 계정 유지, 만료·중지·기존 연결 차단, 후보·물량별 권한 격리, 회사 수정·탈퇴 차단, 인수 요청부터 QR 입고·결과 기록·다음 후보까지의 연속 검증이다.
