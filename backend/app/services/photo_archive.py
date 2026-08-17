import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ExternalPhotoFile, Rug
from app.services.fingerprints import payload_fingerprint

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
ARTICLE_FILENAME = re.compile(r"^(?P<article>[^_]+?)(?:_(?P<number>\d+))?$")


@dataclass(frozen=True)
class ArchiveCandidate:
    rug_id: uuid.UUID
    article: str
    relative_path: str
    checksum: str
    format: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class ArchiveScanResult:
    scanned_files: int
    matched_files: int
    created: int
    updated: int
    unchanged: int
    missing: int


def article_from_filename(filename: str) -> str | None:
    path = Path(filename)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    match = ARTICLE_FILENAME.fullmatch(path.stem)
    return match.group("article") if match else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_metadata(path: Path) -> tuple[int | None, int | None, str]:
    extension = path.suffix.lower().lstrip(".")
    try:
        with Image.open(path) as image:
            return image.width, image.height, (image.format or extension).lower()
    except (UnidentifiedImageError, OSError):
        return None, None, extension


class PhotoArchiveScanner:
    def __init__(self, session: AsyncSession, source: str = "smb_archive") -> None:
        self.session = session
        self.source = source

    async def scan(self, root: Path) -> ArchiveScanResult:
        if not root.is_dir():
            raise FileNotFoundError(f"SMB photo archive недоступен: {root}")
        async with self.session.begin():
            articles = {
                article: rug_id
                for article, rug_id in (
                    await self.session.execute(
                        select(Rug.article, Rug.id).where(Rug.article.is_not(None))
                    )
                ).all()
            }
        scanned = 0
        candidates: dict[tuple[uuid.UUID, str], ArchiveCandidate] = {}
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            scanned += 1
            article = article_from_filename(path.name)
            rug_id = articles.get(article) if article is not None else None
            if rug_id is None:
                continue
            checksum = _sha256(path)
            width, height, image_format = _image_metadata(path)
            relative_path = path.relative_to(root).as_posix()
            candidate = ArchiveCandidate(
                rug_id=rug_id,
                article=article,
                relative_path=relative_path,
                checksum=checksum,
                format=image_format,
                width=width,
                height=height,
            )
            key = (rug_id, checksum)
            current = candidates.get(key)
            if current is None or relative_path < current.relative_path:
                candidates[key] = candidate

        now = datetime.now(UTC)
        created = updated = unchanged = missing = 0
        async with self.session.begin():
            existing = list((await self.session.scalars(
                select(ExternalPhotoFile).where(ExternalPhotoFile.source == self.source).with_for_update()
            )).all())
            by_key = {(item.rug_id, item.checksum): item for item in existing}
            by_current_path = {
                item.relative_path: item for item in existing if item.is_current
            }
            seen_ids: set[uuid.UUID] = set()
            for key, candidate in candidates.items():
                record = by_key.get(key)
                fingerprint = payload_fingerprint(candidate.__dict__)
                if record is None:
                    replaced_path = by_current_path.get(candidate.relative_path)
                    if replaced_path is not None:
                        replaced_path.is_current = False
                        replaced_path.missing_since = now
                    record = ExternalPhotoFile(
                        rug_id=candidate.rug_id,
                        source=self.source,
                        article=candidate.article,
                        relative_path=candidate.relative_path,
                        checksum=candidate.checksum,
                        fingerprint=fingerprint,
                        format=candidate.format,
                        width=candidate.width,
                        height=candidate.height,
                        is_current=True,
                        last_seen_at=now,
                    )
                    self.session.add(record)
                    await self.session.flush()
                    created += 1
                elif record.fingerprint != fingerprint or not record.is_current:
                    record.article = candidate.article
                    record.relative_path = candidate.relative_path
                    record.fingerprint = fingerprint
                    record.format = candidate.format
                    record.width = candidate.width
                    record.height = candidate.height
                    record.is_current = True
                    record.last_seen_at = now
                    record.missing_since = None
                    updated += 1
                else:
                    record.last_seen_at = now
                    unchanged += 1
                seen_ids.add(record.id)
            for record in existing:
                if record.is_current and record.id not in seen_ids:
                    record.is_current = False
                    record.missing_since = now
                    missing += 1
        return ArchiveScanResult(scanned, len(candidates), created, updated, unchanged, missing)
