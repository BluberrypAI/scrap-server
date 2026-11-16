# R코드부터 업체 검토까지 연결 검사 — 2026-11-16

**문진 → R유형 조회 → 화면 → 물량 저장 → 후보 전체 Azure 검토가 연결됐습니다.**
법령표에 적힌 유형을 전달하는 기능입니다. 실제 업체 허가나 이번 물량의 반입을 자동 승인하지 않습니다.

## 무엇을 고쳤나요?

1. diagnosis가 일반 플라스틱·금속 **14개 분류번호**의 R유형·분석 조건·원문을 반환합니다. R-10의 중복 조건을 보존합니다.
2. server가 기업 소유 문진의 번호·판정 버전·법 기준일을 대조하고 물량에 저장합니다. 오래된 확정 건은 원래 판정을 바꾸지 않고 보충 조회합니다.
3. web의 `재활용 유형 확인`에서 유형·조건·법령 링크를 확인합니다. 물량을 등록하고 재접속해도 남습니다.
4. 후보 전체에 같은 유형표와 출처를 전달합니다. 검토 중 문진/R자료가 바뀌거나 이전 검토에 R자료가 빠졌으면 재검토하도록 합니다.
5. B가 처리한 뒤에는 실제 산출물을 사용하고 A의 분류/R유형을 자동 적용하지 않습니다.
6. 넷스파 PA6 어망·대한제강 녹산 철스크랩의 공개 원문을 대조해 사업장·투입물·공정 근거를 보강했습니다. 업체별 통과 예외 규칙은 없습니다.

## 실제로 어디까지 돌렸나요?

| 검사 | 결과 |
| --- | --- |
| 새 버튼 문진 | 18건, 일반 번호 12종. 예상 번호와 전부 일치 |
| 형태 선택 | 56조합 중 53조합에 후보. 3조합은 후보 없음 안내 |
| 최신 Edge 화면 | 59/59 통과. 56형태의 R유형·원문 표시, 미지원 3종 안내 |
| 위험성 문진 | 11/11 일반 후보로 우회하지 않고 보류 |
| 실제 Azure 전체 재검토 | 53조합·294개 후보별 결과, 서로 다른 연결 98개. R전달·후보 누락 오류 0 |
| 최종 공개 근거 판정 | 확인 56회 / 근거 부족 238회 / 호출 오류 0회 |
| 원문 대조 2건 | 별도 실호출에서 둘 다 `reviewed/form_mentioned`. 전체 재검토에서도 각각 확인 |
| 실제 물량 UI | 철스크랩 100kg 합성 물량을 버튼으로 등록 → 새로고침 → AI 검토 → DB 재조회·화면 새로고침. R유형·출처·검토 결과 유지, 후보 2개 모두 결과 표시 |

실제 HTTP와 Azure를 사용했으며 브라우저 응답은 모킹하지 않았습니다. 문진 18건의 입력은 합성 시험용이며 법령 전문가가 인정한 정답셋을 뜻하지 않습니다.

전체 Azure 검사는 이전에 확정한 문진을 사용해 **기존 건의 R유형 보충 연결**도 확인했습니다. 새 문진 18건·최종 물량 UI 검사는 새 확정 결과로 실행했습니다.

최초 실행에는 호출 미완료 9회가 있었습니다. 해당 PP 2조합만 재시도했습니다. 위 수치는 재시도 후 최종 결과이며 최초 성공률이나 모델 정확도 점수가 아닙니다. 근거 부족 결과를 통과할 때까지 반복하지 않았습니다.

## 코드·DB 검사

- server: SQLite **463**, PostgreSQL 17 **463** 통과. 분류/R유형 변경 중 AI 응답 무효화, 구버전 검토 차단, A→B 직접 종료 및 A→B→C의 R전달 분리를 포함합니다.
- diagnosis: SQLite **669**, PostgreSQL 17 **669** 통과. 골든 16/16, 기존 4,281 판정표 회귀 결과 유지. OpenAPI·원본 규칙 빌드 검사 통과.
- route: **545 passed, 72 skipped, 24 subtests**. PA6/PA66·다른 사업장·반입 제한 등 음성 사례와 후보별 R문맥 전달 검사 포함. test/Neo4j CI 통과.
- web: **49개** 검사 및 production/Docker 빌드 통과. 기존 지도·3D 번들 크기 경고는 남아 있습니다.
- DB 마이그레이션 추가 없음. 최신 server/seed 이미지로 **52사업장·63공정·109연결·106출처** 재적재.

## 팀 적용

[diagnosis #23](https://github.com/BluberrypAI/scrap-diagnosis/pull/23), [server #47](https://github.com/BluberrypAI/scrap-server/pull/47), [route #61](https://github.com/BluberrypAI/scrap-route/pull/61), [web #46](https://github.com/BluberrypAI/scrap-web/pull/46), [infra #5](https://github.com/BluberrypAI/scrap-infra/pull/5)를 함께 적용합니다. PR은 병합하지 않았습니다.

infra에서 `docker compose up -d --build` → `docker compose run --rm server-seed`. 브라우저는 **http://localhost:5178**입니다. 기존 PG16 데이터 볼륨에 PG17을 바로 연결하지 않습니다.

## 재현

server 레포에서 개발용 로그인·Azure가 설정된 로컬 통합 환경에 실행합니다. 아래 검사는 합성 문진/물량을 생성하고 Azure를 호출합니다. 실물량에는 실행하지 않습니다.

```powershell
uv run --project backend python scripts/audit_diagnosis_routes.py --help
uv run --project backend python scripts/audit_case_reviews.py --input <문진검사.json> --output <AI검사.json> --all-forms --delay 10
uv run --with playwright --project backend python scripts/audit_route_browser.py --input <문진검사.json> --output <화면검사.json>
uv run --with playwright --project backend python scripts/audit_recycling_lot_browser.py --input <문진검사.json> --output <물량검사.json>
```

호출 실패가 있다면 `audit_case_reviews.py`에 `--resume <AI검사.json>`을 추가합니다. 이미 완료된 정상 결과는 다시 호출하지 않습니다. 물량 UI 검사는 아직 물량을 만들지 않은 새 철스크랩 문진으로 실행합니다.

[R유형 전달 계약](r-code-handoff.md) · [2건 원문 대조](registry-screen/two-case-source-review-20261116.md) · [조합별 수치·원본 검사 파일 해시](r-code-flow-audit-20261116.json)

## 여전히 구분할 것

- R표 14번호와 실제 문진의 12번호는 다른 범위입니다. 법령표 조회만으로 미지원 공정의 업체가 생기지 않습니다.
- 294회는 반복되는 후보별 결과이며 294개 업체가 아닙니다. 109개 전체 연결 중 이번 첫 공정 문진에서 도달한 서로 다른 연결은 98개입니다.
- 일반 PE 베일 2조합·PS 베일 1조합은 후보가 없습니다. PE **필름 베일**은 별도의 공개 실증 사례입니다. PU폼·고무·페놀은 미지원 상태를 유지합니다.
- 실제 시설 허가·이번 물량의 규격·여유 용량·업체 수락은 별도 확인입니다. `dispatch_approved=false`를 유지하며 독립 전문가 정확도 평가는 아직 없습니다.
- 이번 실제 웹 검사는 문진→후보 검토·물량 저장 범위입니다. 기업 간 QR은 기존 7개 합성 시나리오와 이번 자동 회귀 검사로 구분합니다. 모든 소재를 실제 업체에 배송했다는 뜻이 아닙니다.

문서 영향 점검: README·명세·작업 목록·연동 설명 갱신. 에이전트 지침과 레포 역할 변경 없음.
