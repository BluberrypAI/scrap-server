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

- [x] Allow merge commits (릴리스용)
- [x] Allow squash merging (작업 브랜치용)
- [ ] Allow rebase merging
- [x] Automatically delete head branches

### 4.4 브랜치 보호 규칙

Settings → Branches → **Add classic branch protection rule**

> 상태 확인 항목(`backend`)은 CI가 한 번 이상 실행된 뒤에 검색됨. 첫 push 후 PR을 하나 열어 CI를 돌린 다음 설정함.

**develop**

| 항목 | 설정 |
| --- | --- |
| Branch name pattern | `develop` |
| Require a pull request before merging | ✅ |
| └ Require approvals | ✅ 1명 (팀원끼리 리뷰. 혼자 작업 중이면 0) |
| Require status checks to pass before merging | ✅ `backend` |
| └ Require branches to be up to date before merging | ✅ |
| Do not allow bypassing the above settings | ✅ (관리자도 PR 필수) |
| Allow force pushes / Allow deletions | ❌ |

**main**

| 항목 | 설정 |
| --- | --- |
| Branch name pattern | `main` |
| Require a pull request before merging | ✅ |
| └ Require approvals | ❌ 0명 (본인 PR은 본인이 승인할 수 없으므로) |
| Require status checks to pass before merging | ✅ `backend` |
| Restrict who can push to matching branches | ✅ **서버 담당자 계정만 추가** (이 계정만 main에 병합 가능) |
| Do not allow bypassing the above settings | ✅ |
| Allow force pushes / Allow deletions | ❌ |

### 4.5 라벨

Issues → Labels에 `feat`, `fix`, `chore`, `docs` 라벨 생성 (이슈 템플릿이 자동으로 붙임. 라벨이 없는 레포에서는 붙지 않음)

## 5. AI 에이전트 규칙

1. develop, main에서 직접 커밋하지 않고 위 규칙의 작업 브랜치를 만듦
2. push, PR 생성, 병합은 사용자가 요청할 때만 함
3. PR 본문은 `.github/pull_request_template.md`를 채움

## 6. 다른 레포 초기 설정 (서버 담당자, 1회)

| 레포 | 할 일 |
| --- | --- |
| `.github` | 조직에 `.github` 이름의 **공개** 레포 생성 → 로컬 `../.github` 폴더(CONTRIBUTING.md, `.github/ISSUE_TEMPLATE/`, 기본 PR 템플릿)를 push. 조직 기본 이슈 템플릿이 Private 레포에 적용되지 않았으므로 **각 레포에도 `.github/ISSUE_TEMPLATE/`을 복사함** (`cp -r ../.github/.github/ISSUE_TEMPLATE .github/`) |
| `ai` | 4.2~4.5와 같은 설정 + `.github/CODEOWNERS`에 `/schemas/ @<서버담당자 GitHub ID>` (스키마 폴더 이름은 ai 레포 구조에 맞춤), 브랜치 보호에서 **Require review from Code Owners** 체크 |
| `infra` | develop·main 보호는 같은 방식. 통합 compose는 형제 폴더(`../server/backend`, `../ai`, `../frontend`)를 빌드 경로로 사용 |
| `frontend` | 프론트 팀과 합의해 적용 (develop을 쓰지 않기로 하면 main 보호만) |

team-conventions.md를 바꾸면 `.github` 레포의 `CONTRIBUTING.md`에도 같은 내용을 반영함.
