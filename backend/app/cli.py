import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.services.photo_archive import PhotoArchiveScanner


async def scan_photo_archive(root: Path) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            result = await PhotoArchiveScanner(session).scan(root)
        print(
            "scan завершён:",
            f"scanned={result.scanned_files}",
            f"matched={result.matched_files}",
            f"created={result.created}",
            f"updated={result.updated}",
            f"unchanged={result.unchanged}",
            f"missing={result.missing}",
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan-photo-archive")
    scan.add_argument("--root", type=Path, required=True, help="Путь к read-only SMB mount")
    arguments = parser.parse_args()
    if arguments.command == "scan-photo-archive":
        asyncio.run(scan_photo_archive(arguments.root))


if __name__ == "__main__":
    main()
