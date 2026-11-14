# 전국 명부에서 플라스틱 재활용업체 찾기

**9,604행 전체를 선별했고, 그중 일부 사업장을 공개 원문과 대조해 실제 공정 후보에 연결했습니다.** 명부 선별을 끝낸 것과 모든 업체의 처리 능력 확인을 마친 것은 다릅니다.

## 파일별 의미

| 파일 | 내용 |
| --- | --- |
| [all-plastic-rows.csv](all-plastic-rows.csv) | 원본 전체에서 플라스틱 관련 문구·코드가 있는 4,359행 |
| [recycler-research-queue.csv](recycler-research-queue.csv) | 그중 재활용업 2,084행. 같은 이름·주소의 행은 `site_cluster`로 묶음(1,935개 묶음) |
| [summary.json](summary.json) | 원본 URL·SHA256·선별 수·업종별 수 |
| [role-review.json](role-review.json) | 기존 역할 추정 21개 각각의 재검토 결과: 2개 근거 보강, 19개 추정 유지 |
| [live-validation.json](live-validation.json) | 로컬 서버/PostgreSQL 48개 조회 및 Azure 실제 11개 검토. 입력은 합성이고 근거는 공개 요약 |
| [추가 조사 보류 기록](held-leads.md) | 검색 결과가 있어도 자동 연결하지 않은 사례와 필요한 다음 자료 |

원본은 [전국폐기물처리업소표준데이터](https://www.data.go.kr/data/15114147/standard.do)의 기존 확보 JSON입니다. 파일 버전의 해시는 `summary.json`에 기록되어 있습니다. 이번에 전국 명부 자체를 최신 버전으로 교체한 것은 아닙니다.

## 어떻게 추렸나

1. 모든 행의 처리폐기물 필드에서 `51-03` 계열 코드, 폐합성수지, 플라스틱, 폐비닐, 스티로폼을 검색합니다.
2. 업종을 나눕니다. 재활용업은 2,084행, 수집·운반만 있는 행은 2,119행, 처분업은 156행입니다. 운반업만 있는 회사를 재활용 공장으로 연결하지 않습니다.
3. 이름과 주소가 모두 같은 행을 하나의 조사 묶음으로 표시합니다. 주소 없는 행은 서로 합치지 않습니다. 법인 동일성이나 허가의 유효성을 판정하는 절차는 아닙니다.
4. 설비 설명이 있는 재활용업 462행을 우선 조사하고, 설명 없는 1,622행은 공정 원문을 찾는 대기열로 둡니다.
5. 회사의 공식 공정·제품 자료 또는 공시를 읽고 해당 사업장 주소를 대조합니다. 이 단계에서 확인한 연결만 별도 공정 참조에 넣습니다. CSV의 `material`, `input_form`, `acceptance`는 여전히 `unknown`입니다.

CSV는 **조사 목록**입니다. `폐합성수지 / 분쇄기`라는 명부 기록을 PP·PE·PET를 모두 받는다는 뜻으로 바꾸지 않습니다. 압축 설비를 보유하거나 베일을 판매하는 것도 압축 베일을 반입한다는 증거가 아닙니다. 현재 공정 참조는 37곳·81개 연결이며, 이름·주소 대조는 `backend/app/domains/treatment/resources/facility-evidence-links.json`에 따로 저장합니다.

## 역할 확인 21개는 어떻게 됐나

- **NPC 화성 2개:** [HDPE 공정 이미지](http://www.npc-chemical.com/images/sub_text_03_1.png), [PP 공정 이미지](http://www.npc-chemical.com/images/sub_text_03_2.png)와 회사 주소를 대조했습니다. PP 분쇄·세척과 HDPE 상자/팔레트 분쇄를 공개 공정 근거로 반영했습니다. HDPE 사례를 LDPE 필름·압축 베일에 확대하지 않습니다.
- **씨엔텍코리아 12개:** [공식 공정](https://cntk.co.kr/page/?pid=process)에 선별·분쇄·펠릿이 있으나 화성·진주 각각의 소재/라인 배정이 불명확합니다. 사업장별 설비표 또는 해당 공장의 확인 자료가 필요합니다.
- **BGF 7개:** 그룹 자료의 재활용 공정과 사업장 정보만으로 예산·화성의 수지별 라인을 확정하지 않았습니다. [2025년 공식 회사소개서](https://bgfecomaterials.com/resources/kr/file/BGFecomaterials_Company_Profile_2025_KR.pdf) 7·11쪽도 확인했으나 사업장별 투입 수지·공정표는 없습니다. 회사 전체 제품 설명을 각 공장의 능력으로 복제하지 않습니다.

## PE·PS 압축 베일

[PRE 2026년 10월 자료](https://www.plasticsrecyclers.eu/wp-content/uploads/2026/10/Mapping-of-plastics-recycling-PRE-October-2026.pdf) 35–38쪽, 47–48쪽에서 일반적인 선별·재활용 흐름을 확인했습니다. 공정 단계는 베일 해체·결속재 제거 → 이물/수지 선별 → 분쇄로 보강했습니다.

다만 **이 자료는 유럽의 일반 공정 설명**입니다. 국내 베일 수령 공장을 증명하지 않습니다. 다음 입력·증빙이 있어야 국내 사업장 연결을 추가할 수 있습니다.

- PE의 HDPE/LDPE 등급 또는 PS 종류와 다른 수지 혼합 여부
- 베일 치수·중량, 철선/밴드 등 결속재, 내용물·이물 상태
- 해당 사업장의 베일 해체·선별 설비와 실제 반입 사례
- 해당 분류번호·원료·형태의 반입 범위 및 수신 기업 확인

따라서 PE 베일 두 번호와 PS 베일은 현재 `no_route`입니다. 공정은 설명할 수 있지만 공장 후보는 비워 둡니다. A→B 이후 B의 실제 산출물이 베일일 때도 동일합니다. 숫자를 늘리기 위해 플레이크·EPS 인고트 업체를 베일 수령 업체로 바꾸지 않았습니다.

## 재현

레포 루트에서 확보한 원본 JSON 경로를 지정합니다. CSV에는 공공 사업장명·주소·업종·폐기물·설비·기준일만 남기며 전화번호·담당자 연락처는 내보내지 않습니다. 명령은 공정 DB를 수정하지 않습니다.

```bash
uv run --project backend python scripts/plastic_registry_screen.py /path/to/national-facility-registry.json --out docs/registry-screen
```

공정 참조를 실제 서버 DB에 반영하는 명령은 별도입니다. 기존 인계 기록과 명부 행은 유지합니다.

```bash
cd backend
uv run python -m app.domains.treatment.import_catalog
uv run python ../scripts/plastic_coverage.py ../docs/plastic-coverage.json
```

이번 검증은 SQLite/PostgreSQL 각각 259개 테스트, 실제 로컬 API 48개 조회, Azure 공개 근거 검토 11개입니다. 자동 테스트의 계정·물량·문진·모델 대역과 실제 업체의 계약·인수를 구분해야 합니다. 모델 검토 11개는 문장 근거 확인 1개, 추가 자료 필요 10개이며 인수 승인은 전부 `false`입니다.
