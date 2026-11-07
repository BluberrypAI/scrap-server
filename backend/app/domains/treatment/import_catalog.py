"""Load the curated process reference and an optional verified facility snapshot."""

import argparse
import asyncio
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.domains.treatment.repository import replace_snapshots


async def run(args):
    async with SessionLocal() as db:
        result = await replace_snapshots(db, args.registry, args.sha256)
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if (args.registry is None) != (args.sha256 is None):
        parser.error("--registry and --sha256 must be provided together")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
