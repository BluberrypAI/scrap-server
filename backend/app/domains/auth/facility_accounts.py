"""운영자용: 처리업체(B·C) 아이디·비밀번호 계정 발급 (docs/specs/facility-password-login.md).

업체 정보는 새로 받지 않고 DB의 처리 공정표 스냅샷(treatment_snapshots processes)에서 가져옴.
한 번 실행으로 사용자(provider=password)·기업·업체 연결(workflow_facility_accounts)을 만듦.
같은 아이디로 다시 실행하면 비밀번호와 연결만 갱신하고 기업 정보는 그대로 둠.

배포 DB에 쓰려면 DATABASE_URL을 운영 DB로 두고 backend/에서 실행함.

    uv run python -m app.domains.auth.facility_accounts --list
    uv run python -m app.domains.auth.facility_accounts \\
        --login-id sarom-hwaseong --facility sarom-hwaseong-2 \\
        --contact-email manager@example.com
    # 비밀번호는 입력 프롬프트로 받음. 자동화할 때는 --password-stdin

연결은 synthetic=false로 저장해서 운영(DEMO_FACILITY_BINDINGS 없이)에서도 수신 업체로 보임.
확인 근거 칸에는 명령으로 발급한 계정임을 기록함(--verification-reference로 바꿀 수 있음).
화면에서 숨기고 싶은 시험 계정이면 --synthetic을 줌.
"""

import argparse
import asyncio
import getpass
import sys
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import passwords
from app.db import all_models as _all_models  # noqa: F401
from app.domains.auth.service import PASSWORD_PROVIDER, normalize_login_id
from app.domains.companies import service as company_service
from app.domains.companies.models import Company
from app.domains.companies.schemas import CompanyCreate
from app.domains.transport.models import WorkflowFacilityAccount
from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.repository import read_reference
from app.domains.users import repository as user_repo

DEFAULT_INDUSTRY = "폐기물 처리·재활용업"
DEFAULT_SITE_FACILITIES = ["폐기물 처리시설"]
PROVISIONED_REFERENCE = "facility login account provisioned by the SCRAP team (facility_accounts)"


class ProvisionError(Exception):
    pass


@dataclass
class ProvisionResult:
    login_id: str
    company_name: str
    created_user: bool
    created_company: bool
    facility_keys: list[str]
    synthetic: bool


async def list_facilities(db: AsyncSession) -> list[tuple[str, str, str]]:
    """(업체 키, 사업장명, 기업명) 목록."""
    reference, _ = await read_reference(db)
    organisations = {o.key: o.label for o in reference.organisations}
    return [(f.key, f.label, organisations.get(f.organisation, "")) for f in reference.facilities]


async def provision(
    db: AsyncSession,
    *,
    login_id: str,
    password: str,
    facility_keys: list[str],
    contact_email: str | None = None,
    industry: str = DEFAULT_INDUSTRY,
    site_facilities: list[str] | None = None,
    verification_reference: str | None = None,
    synthetic: bool = False,
    force: bool = False,
) -> ProvisionResult:
    """계정·기업·업체 연결을 한 트랜잭션으로 만들거나 갱신함. 실패하면 아무것도 쓰지 않음."""
    login_id = normalize_login_id(login_id)
    if not login_id:
        raise ProvisionError("아이디가 비어 있음")
    if not passwords.MIN_LENGTH <= len(password) <= passwords.MAX_LENGTH:
        raise ProvisionError(
            f"비밀번호는 {passwords.MIN_LENGTH}자 이상 {passwords.MAX_LENGTH}자 이하여야 함"
        )
    keys = list(dict.fromkeys(facility_keys))
    if not keys:
        raise ProvisionError("--facility를 하나 이상 지정해야 함")

    try:
        reference, _ = await read_reference(db)
    except TreatmentError as exc:
        raise ProvisionError(f"처리 공정표 스냅샷을 읽을 수 없음: {exc}") from exc
    facilities = {f.key: f for f in reference.facilities}
    unknown = [k for k in keys if k not in facilities]
    if unknown:
        raise ProvisionError(f"스냅샷에 없는 업체 키: {', '.join(unknown)} (--list로 확인)")
    organisations = {o.key: o.label for o in reference.organisations}

    user = await user_repo.get_user_by_identity(db, PASSWORD_PROVIDER, login_id)
    created_user = user is None
    company = None if created_user else await company_service.get_company_by_user(db, user.id)

    # 다른 기업에 이미 연결된 업체는 기본으로 바꾸지 않음
    bindings = {k: await db.get(WorkflowFacilityAccount, k) for k in keys}
    taken = [
        k for k, b in bindings.items() if b and (company is None or b.company_id != company.id)
    ]
    if taken and not force:
        raise ProvisionError(f"다른 기업에 연결된 업체 키: {', '.join(taken)} (바꾸려면 --force)")

    if created_user:
        user = await user_repo.create_user(
            db,
            provider=PASSWORD_PROVIDER,
            provider_subject=login_id,
            email=contact_email,
            name=None,
        )
    user.password_hash = passwords.hash_password(password)

    created_company = company is None
    if created_company:
        primary = facilities[keys[0]]
        email = contact_email or (login_id if "@" in login_id else None)
        if not email:
            raise ProvisionError("새 기업에는 --contact-email이 필요함 (아이디가 이메일이 아님)")
        try:
            data = CompanyCreate(
                company_name=organisations.get(primary.organisation) or primary.label,
                contact_email=email,
                industry=industry,
                site_name=primary.label,
                site_address=primary.address or primary.region,
                site_facilities=site_facilities or DEFAULT_SITE_FACILITIES,
                site_latitude=primary.latitude,
                site_longitude=primary.longitude,
            )
        except ValidationError as exc:
            raise ProvisionError(f"기업 정보가 올바르지 않음: {exc}") from exc
        company = Company(
            user_id=user.id,
            **data.model_dump(exclude={"main_waste_types"}),
            main_waste_types=[],
        )
        db.add(company)
        await db.flush()

    for key, binding in bindings.items():
        if binding is None:
            binding = WorkflowFacilityAccount(facility_key=key)
            db.add(binding)
        binding.company_id = company.id
        binding.synthetic = synthetic
        binding.verification_reference = verification_reference or PROVISIONED_REFERENCE

    await db.commit()
    return ProvisionResult(
        login_id=login_id,
        company_name=company.company_name,
        created_user=created_user,
        created_company=created_company,
        facility_keys=keys,
        synthetic=synthetic,
    )


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("비밀번호: ")
    if first != getpass.getpass("비밀번호 확인: "):
        sys.exit("비밀번호가 서로 다름")
    return first


async def _run(args: argparse.Namespace) -> int:
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        if args.list:
            try:
                rows = await list_facilities(db)
            except TreatmentError as exc:
                print(f"처리 공정표 스냅샷을 읽을 수 없음: {exc}", file=sys.stderr)
                return 1
            for key, label, org in rows:
                print(f"{key}\t{label}\t{org}")
            return 0
        try:
            result = await provision(
                db,
                login_id=args.login_id,
                password=_read_password(args.password_stdin),
                facility_keys=args.facility,
                contact_email=args.contact_email,
                industry=args.industry,
                site_facilities=args.site_facility or None,
                verification_reference=args.verification_reference,
                synthetic=args.synthetic,
                force=args.force,
            )
        except ProvisionError as exc:
            print(f"실패: {exc}", file=sys.stderr)
            return 1
    print(
        f"{'생성' if result.created_user else '갱신'} {result.login_id} -> {result.company_name}"
        f" ({'새 기업' if result.created_company else '기존 기업'})"
    )
    shown = "synthetic, 운영 화면에서 숨김" if result.synthetic else "운영 화면에 보임"
    for key in result.facility_keys:
        print(f"  연결 {key} ({shown})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="연결할 수 있는 업체 키 목록 출력")
    parser.add_argument("--login-id", help="로그인 아이디 (소문자로 저장)")
    parser.add_argument(
        "--facility", action="append", default=[], help="업체 키 (여러 번 지정 가능)"
    )
    parser.add_argument("--contact-email", help="담당 이메일 (새 기업에 필요)")
    parser.add_argument("--industry", default=DEFAULT_INDUSTRY, help="업종")
    parser.add_argument(
        "--site-facility", action="append", default=[], help="사업장 시설 이름 (여러 번)"
    )
    parser.add_argument(
        "--verification-reference", help="확인 근거 칸에 남길 문구 (기본: 명령으로 발급한 계정)"
    )
    parser.add_argument(
        "--synthetic", action="store_true", help="시험용으로 저장 (운영 화면에서는 숨김)"
    )
    parser.add_argument("--force", action="store_true", help="다른 기업에 연결된 업체도 옮김")
    parser.add_argument(
        "--password-stdin", action="store_true", help="비밀번호를 표준 입력 첫 줄에서 읽음"
    )
    args = parser.parse_args()
    if not args.list and not (args.login_id and args.facility):
        parser.error("--login-id와 --facility를 지정해야 함 (목록은 --list)")
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
