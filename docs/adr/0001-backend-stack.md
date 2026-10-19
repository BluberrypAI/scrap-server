# ADR 0001: 백엔드 기술스택

| 항목 | 내용 |
| --- | --- |
| 상태 | 채택 (배포 대상은 보류) |
| 날짜 | 2026-10-15 |

## 결정

| 영역 | 선택 | 비교안 | 선정 이유 |
| --- | --- | --- | --- |
| 언어 | Python | Node.js, Java | AI·데이터 라이브러리와 Azure SDK 지원이 가장 풍부함 |
| 프레임워크 | FastAPI | Django(DRF), Flask | 비동기 기본 지원으로 LLM 호출에 유리함. Pydantic 스키마로 입출력을 검증하고 OpenAPI 문서로 다른 레포와 형식을 공유함 |
| DB | PostgreSQL | MySQL, Cosmos DB | 관계형 데이터와 JSONB(유연한 항목)를 함께 처리함 |
| ORM | SQLAlchemy 2.0 + Alembic | SQLModel | 비동기와 복잡한 조회 지원, 마이그레이션 도구가 성숙함 |
| 패키지 | uv | pip, Poetry | 설치가 빠르고 lock 파일로 팀원 간 버전을 맞춤 |
| 인증 | Authlib + JWT 쿠키 | Entra External ID, Auth0 | Google과 MS 개인 계정을 모두 지원하고 추가 비용이 없음 |
| 배포 | App Service (기본안, 보류) | Container Apps, VM | 서버 관리가 필요 없고 시연에 안정적임. Dockerfile 유지로 전환이 쉬움 |

AI 구성(에이전트, RAG, 지식그래프, MCP 서버)은 ai 레포에서 결정함 (ADR 0002).

## 영향

- 모든 입출력은 Pydantic 스키마로 정의하고, LLM 출력도 같은 스키마로 검증함
- **로컬 개발 표준은 docker compose의 PostgreSQL**임 (2026-10-17, 팀 전원 Docker 사용). SQLite는 Docker 없이 빠르게 확인할 때와 단위 테스트(`uv run pytest`)용 보조 수단이며, CI는 PostgreSQL로 검증함
- PostgreSQL 전용 기능(JSONB, pgvector 등)은 도입할 수 있음. 도입하면 해당 기능의 SQLite 실행은 지원하지 않고, 관련 테스트는 PostgreSQL에서만 돌도록 표시함
- DB 연결은 `DATABASE_URL`, `DB_SSL`, `DB_POOL_SIZE` 환경변수로만 바꿈 (로컬 → Azure 이전 시 코드 변경 없음)
- 배포 대상은 Azure 제공 자원 확인(T-008) 후 이 ADR을 갱신함
