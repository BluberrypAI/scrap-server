"""시험·시연용: 로그인 계정의 기업을 처리 업체에 연결함 (synthetic).

기업 간 인계(/workflow)는 업체(facility_key)에 연결된 수신 기업 계정이 있어야
인수 요청을 보낼 수 있음.
운영에서는 실제 시설 증빙으로 연결해야 하므로 이 스크립트는 APP_ENV=local·test에서만 실행됨.
발표 시연처럼 운영에서 써야 하면 DEMO_FACILITY_BINDINGS=true로 켜고 --email·--facility를 직접 지정함
(기본 시험 계정 example.com은 운영에 없음). 연결은 synthetic으로 저장돼 화면에 시연용으로 표시됨.

사용 순서
1. 웹에서 개발용 로그인으로 각 이메일에 로그인하고 기업 등록(온보딩)까지 마침
2. backend/에서 실행

    uv run python -m app.domains.transport.dev_accounts   # 기본 시험 계정(PP·PE·알루미늄)
    # 다른 계정·업체 연결
    uv run python -m app.domains.transport.dev_accounts
        --email b@example.com --facility sarom-hwaseong-2
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.db import all_models as _all_models  # noqa: F401
from app.db.session import SessionLocal
from app.domains.companies.models import Company
from app.domains.transport.models import WorkflowFacilityAccount
from app.domains.users.models import User

# 기본 연결: 선별·파쇄 담당과 펠렛·컴파운드 담당 (docs/pp-company-e2e.md의 시험 계정).
# PE는 PP와 같은 업체를 쓰고, 알루미늄캔은 판재·잉곳 업체를 별도 계정에 연결함
DEFAULT_BINDINGS = {
    "pp-sort@example.com": ["jungang-gongju", "npc-chemical-hwaseong", "sarom-hwaseong-2"],
    "pp-pellet@example.com": [
        "veolia-doksan-hwaseong",
        "bgf-yesan",
        "bgf-hwaseong",
        "veolia-dspl-hwaseong",
    ],
    "al-can@example.com": ["novelis-yeongju", "ulsan-aluminium"],
}
REFERENCE = "synthetic demo binding (dev_accounts), not a real company link"


async def bind(bindings: dict[str, list[str]]) -> int:
    missing = 0
    async with SessionLocal() as db:
        for email, facilities in bindings.items():
            company = await db.scalar(
                select(Company).join(User, Company.user_id == User.id).where(User.email == email)
            )
            if company is None:
                print(f"건너뜀 {email}: 개발용 로그인 후 기업 등록을 먼저 해 주세요")
                missing += 1
                continue
            for key in facilities:
                row = await db.get(WorkflowFacilityAccount, key)
                if row is None:
                    row = WorkflowFacilityAccount(facility_key=key)
                    db.add(row)
                row.company_id = company.id
                row.synthetic = True
                row.verification_reference = REFERENCE
                print(f"연결 {key} -> {company.company_name} ({email})")
        await db.commit()
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--email", help="연결할 개발 로그인 이메일")
    parser.add_argument(
        "--facility", action="append", default=[], help="업체 키 (여러 번 지정 가능)"
    )
    args = parser.parse_args()
    settings = get_settings()
    if not settings.synthetic_bindings_allowed:
        sys.exit("APP_ENV=local·test이거나 DEMO_FACILITY_BINDINGS=true일 때만 실행할 수 있음")
    if bool(args.email) != bool(args.facility):
        parser.error("--email과 --facility는 함께 지정해야 함")
    if settings.app_env == "prod" and not args.email:
        parser.error("운영에서는 --email과 --facility를 직접 지정해야 함")
    bindings = {args.email: args.facility} if args.email else DEFAULT_BINDINGS
    sys.exit(1 if asyncio.run(bind(bindings)) else 0)


if __name__ == "__main__":
    main()
