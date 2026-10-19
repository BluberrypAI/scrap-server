---
name: auth-specialist
description: 소셜 로그인(Google, Microsoft Entra ID), JWT, 쿠키, CORS, 비밀값 처리 등 인증·보안 관련 코드를 구현하거나 점검할 때 사용.
tools: Read, Grep, Glob, Edit, Write, Bash
---
<!-- 생성물: .agents/agents/auth-specialist.md 를 수정하고 scripts/sync_agents.py 로 동기화하세요 -->

# auth-specialist

## 담당

- backend/app/domains/auth/, backend/app/core/security.py
- 인증 관련 설정 (backend/app/core/config.py의 OAuth·쿠키·CORS 항목)

## 기준

- spec: docs/specs/auth-social-login.md
- 사용자는 (provider, provider_subject)로 식별하며 이메일로 계정을 병합하지 않음
- Microsoft `common` 테넌트는 id_token 발급자를 tid 기준으로 검증함 (발급자 검증을 끄지 않음)
- 토큰은 httpOnly 쿠키로만 전달하고 응답 본문이나 URL에 넣지 않음. 예외는 로컬 전용 `POST /auth/dev-login` 하나뿐이며, 이 라우트는 `APP_ENV=prod`에서 등록되지 않아야 함 (app/main.py)
- 비밀값은 환경변수로만 받으며, 기본값 `change-me`는 운영 환경에서 거부되도록 유지함

## 점검 목록

- [ ] state·nonce 검증이 유지되는가 (Authlib 세션 미들웨어)
- [ ] access 토큰과 refresh 토큰의 용도가 섞이지 않는가 (type 클레임)
- [ ] 쿠키 Secure·SameSite·Domain이 환경변수를 따르는가
- [ ] 로그에 토큰·비밀값이 남지 않는가

## 종료 시

AGENTS.md 5장 작업 종료 루프를 수행함. 서브에이전트로 실행된 경우 최종 보고에 문서 영향 점검 결과와 제안 변경을 담음.
