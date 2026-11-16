"""Permanently delete users whose withdrawal grace period has passed.

Run once a day: `uv run python -m app.domains.users.purge` (docs/specs/account-withdrawal.md)
"""

import asyncio

from app.db.session import SessionLocal, engine
from app.domains.users.service import purge_withdrawn_users


async def main() -> None:
    async with SessionLocal() as db:
        count = await purge_withdrawn_users(db)
    await engine.dispose()
    print(f"Purged {count} withdrawn user(s)")


if __name__ == "__main__":
    asyncio.run(main())
