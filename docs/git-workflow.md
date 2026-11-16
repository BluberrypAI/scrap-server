# Git Workflow (server 레포)

> 브랜치 전략, 커밋 규칙, PR·릴리스 절차는 **조직 공통 규칙 [team-conventions.md](team-conventions.md)** 를 따름.
> 이 문서는 그 규칙을 server 레포에 적용하는 방법(저장소 연결, GitHub 설정, AI 에이전트 규칙)만 다룸.

## 1. 브랜치

team-conventions.md 3장. 요약: `feat/ fix/ docs/ chore/ refactor/ test/` → develop (PR 필수) → main (서버 담당자만, 배포용). 긴급 수정은 `hotfix/`.

## 2. 커밋 메시지

team-conventions.md 3장. 예: `feat: add company update API`

## 3. 작업 흐름과 릴리스

team-conventions.md 4장(PR), 6장(배포·릴리스). server 레포의 릴리스는 ai 레포 다음에 배포함 (형식이 바뀐 경우).

릴리스 PR을 병합한 뒤 태그:

```bash
git switch main && git pull
git tag v0.1.0
git push origin v0.1.0
```

## 4. GitHub 설정 (저장소 관리자가 한 번 적용)

### 4.1 저장소 연결 (최초 1회, 저장소 루트에서)

```bash
git init -b main
git add .
git status                      # .env, local.db가 목록에 없는지 확인
git commit -m "chore: initial project setup"
git remote add origin https://github.com/<조직>/<저장소>.git
git push -u origin main
git switch -c develop
git push -u origin develop
```

### 4.2 기본 브랜치

Settings → General → Default branch → **develop**으로 변경
(PR을 열 때 기본 대상이 develop이 되어 실수로 main에 PR을 올리는 일을 줄임)

### 4.3 병합 방식

Settings → General → Pull Requests

- [x] Allow merge commits (작업 PR, 릴리스 PR 모두)
- [ ] Allow squash merging
- [ ] Allow rebase merging
- [x] Automatically delete head branches

### 4.4 브랜치 보호 룰셋

Settings → Rules → Rulesets → **New ruleset → New branch ruleset**

> ⚠️ 조직이 무료 플랜이고 레포가 Private이면 룰셋은 저장만 되고 **강제되지 않음** ("won't be enforced ... until you upgrade to GitHub Team"). 지금은 팀 규칙(team-conventions.md 4장)으로 운영하고, 룰셋은 Team 업그레이드나 Public 전환 시 바로 적용되도록 만들어 둠.
>
> status check 항목은 CI가 한 번 이상 실행된 뒤에 검색됨. PR을 하나 열어 CI를 돌린 다음 설정함.

**develop-protection**

| 항목 | 설정 |
| --- | --- |
| Enforcement status | **Active** |
| Target branches | Include by pattern → `develop` |
| Restrict deletions | ✅ |
| Block force pushes | ✅ |
| Require a pull request before merging | ✅ |
| └ Required approvals | **0** (PR은 필수, 병합은 작성자가 직접) |
| Require status checks to pass | ✅ `backend` (레포별 job 이름은 6장) |

**main-protection**

develop-protection과 같고 다음만 다름.

| 항목 | 설정 |
| --- | --- |
| Target branches | Include by pattern → `main` |
| Restrict updates | ✅ |
| Bypass list | 서버 담당자 계정 추가 (Restrict updates는 병합까지 막으므로 이 계정만 main에 병합 가능) |

## 5. AI 에이전트 규칙

1. develop, main에서 직접 커밋하지 않고 위 규칙의 작업 브랜치를 만듦
2. push, PR 생성, 병합은 사용자가 요청할 때만 함
3. PR 본문은 `.github/pull_request_template.md`를 채움

## 6. 다른 레포 초기 설정 (서버 담당자, 1회)

로컬에서는 모든 레포를 한 폴더 아래에 **나란히** clone함. infra의 통합 compose가 형제 폴더를 빌드 경로로 쓰므로 폴더 이름을 아래와 같이 맞춤.

```bash
git clone https://github.com/resource-ai-team/.github.git .github
git clone https://github.com/resource-ai-team/Re_server.git server
git clone https://github.com/resource-ai-team/Re_AI.git ai
git clone https://github.com/resource-ai-team/Re_client.git frontend
git clone https://github.com/resource-ai-team/Re_infra.git infra
```

| 레포 | 초기화 | CI job | 비고 |
| --- | --- | --- | --- |
| `.github` | `CONTRIBUTING.md`(= team-conventions.md), `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md` | 없음 | **Public**이어야 함. 이슈·PR 템플릿의 원본 |
| `server` | 4.1~4.4 | `backend` | PR 템플릿은 server용(pytest, ruff, 마이그레이션) |
| `ai` | 기존 브랜치가 작업 브랜치 하나뿐이어서 main·develop을 **빈 첫 커밋**에서 만들고, 작업 브랜치는 develop으로 PR | `test` (AI 팀 작성) | CODEOWNERS는 두지 않음 |
| `frontend` | 빈 레포에 README, .gitignore, 템플릿으로 첫 커밋 → main, develop 생성 | `frontend` | `package.json`이 없으면 검사를 건너뛰고 통과 |
| `infra` | frontend와 같음 | `infra` | compose·Bicep 파일이 없으면 검사를 건너뛰고 통과 |

각 레포 공통: 4.2 기본 브랜치, 4.3 병합 방식, 4.4 룰셋(status check는 위 job 이름). 라벨은 쓰지 않음.

**템플릿 복사**: 조직 기본 이슈·PR 템플릿이 Private 레포에 적용되지 않으므로 각 레포에 복사함 (레포 루트에서)

```bash
mkdir -p .github
cp -r ../.github/.github/ISSUE_TEMPLATE .github/
cp ../.github/.github/pull_request_template.md .github/   # server 제외
```

이슈 템플릿의 `name`은 **3글자 이상**이어야 GitHub가 인식함 (예: `기능 (feat)`).

team-conventions.md를 바꾸면 `.github` 레포의 `CONTRIBUTING.md`에도 같은 내용을 반영함.
