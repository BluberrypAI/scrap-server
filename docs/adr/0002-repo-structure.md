# ADR 0002: 조직 레포 구성과 배포 단위

| 항목 | 내용 |
| --- | --- |
| 상태 | 채택 |
| 날짜 | 2026-10-17 |

## 결정

서비스별로 레포를 나누고, 공통 규칙과 통합 실행은 별도 레포에 둠.

| 레포 | 역할 | 배포 |
| --- | --- | --- |
| `.github` | 조직 공통 규칙(CONTRIBUTING), 기본 이슈·PR 템플릿 | 없음 |
| `infra` (현 Main) | 전체 통합 실행 docker-compose, Azure 리소스 정의(Bicep), 함께 배포할 버전 조합 기록 | 없음 (배포 설정 보관) |
| `server` (이 레포) | FastAPI API, 인증, 기업 정보, DB 스키마·마이그레이션 | App Service (기본안) |
| `ai` | 에이전트, MCP 도구 7종 | Azure Functions |
| `frontend` | 웹 화면 | 프론트 팀 결정 |

## 비교안

| 안 | 판단 |
| --- | --- |
| 모노레포 (server+ai 한 레포) | 스키마 불일치를 CI로 잡기 쉬우나, ai 팀원과 server 담당자의 작업·배포 권한을 나누기 어려움 |
| 메타 레포 + git submodule | submodule 갱신 누락이 잦아 소규모 팀에 부담 |
| **서비스 레포 + infra + .github** | 레포별 권한·배포를 분리할 수 있고, 통합 실행은 infra에서 해결. **채택** |

## 규칙

1. server와 ai는 각자 배포함. 둘 사이의 입출력 형식(MCP 도구 스키마)은 **필드 추가만 허용**하고 삭제·이름 변경은 server 담당자와 협의함
2. 형식이 바뀐 릴리스는 **ai를 먼저, server를 나중에** 배포함
3. ai 레포는 CODEOWNERS로 스키마 폴더 변경에 server 담당자 승인을 요구함
4. 통합 확인은 infra 레포의 docker-compose로 함. 각 레포는 infra와 **나란히** clone함 (infra 하위에 넣지 않음)
5. 각 레포의 로컬 compose는 그 레포 단독 개발용으로 유지함 (server: api + db)

## 영향

- 이 레포에서 `mcp_server/`, `knowledge/`, `infra/` 자리를 제거함 (ai, infra 레포 몫)
- AI 지식 기반의 구조와 저장 위치는 ai 레포에서 설계 중임. server DB에 저장할 데이터가 생기면 해당 기능 spec(T-105) 작성 시 ai 팀과 결정함
