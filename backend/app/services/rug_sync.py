import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditEvent, Rug, RugExternalData, RugLocation, RugPhoto
from app.repositories.rugs import (
    AuditRepository,
    RugHistoryRepository,
    RugPhotoRepository,
    RugRepository,
)
from app.schemas.rugs import RugImportRequest, RugPhotoImport
from app.services.fingerprints import payload_fingerprint, to_jsonable

RUG_SOURCE = "1c"
RUG_MUTABLE_FIELDS = (
    "name",
    "status",
    "article",
    "country",
    "composition",
    "width_cm",
    "length_cm",
    "current_location",
    "retail_price",
    "contractor_price",
    "currency",
    "source_updated_at",
    "category",
    "description",
    "weight_kg",
    "stock_qty",
    "stock_unit",
    "retail_price_unit",
    "attributes",
)


@dataclass(frozen=True)
class RugSyncResult:
    result: Literal["created", "updated", "unchanged"]
    rug_id: uuid.UUID
    barcode: str


@dataclass(frozen=True)
class RugSyncConflictError(Exception):
    code: Literal["stale_snapshot", "timestamp_conflict"]
    message: str
    barcode: str
    current_source_updated_at: datetime
    incoming_source_updated_at: datetime

    def as_detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "barcode": self.barcode,
            "current_source_updated_at": self.current_source_updated_at.isoformat(),
            "incoming_source_updated_at": self.incoming_source_updated_at.isoformat(),
        }


class RugSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.rugs = RugRepository(session)
        self.history = RugHistoryRepository(session)
        self.photos = RugPhotoRepository(session)
        self.audit = AuditRepository(session)

    async def upsert(self, request: RugImportRequest) -> RugSyncResult:
        normalized_photos = self._deduplicate_photos(request.photos)
        normalized_locations = self._deduplicate_locations(request.locations)
        version_payload = self._build_version_payload(
            request, normalized_photos, normalized_locations
        )
        fingerprint = payload_fingerprint(version_payload)
        observed_at = datetime.now(UTC)

        async with self.session.begin():
            await self.rugs.acquire_barcode_lock(request.barcode)
            rug = await self.rugs.get_by_barcode(request.barcode, for_update=True)

            if rug is None:
                rug = await self.rugs.add(self._new_rug(request))
                self.history.add(
                    self._new_history(rug.id, version_payload, fingerprint, observed_at)
                )
                await self._sync_photos(rug.id, normalized_photos, observed_at)
                await self._sync_locations(rug.id, normalized_locations, observed_at)
                self.audit.add(
                    self._audit_event(
                        rug.id,
                        action="created",
                        old_data=None,
                        new_data=version_payload,
                    )
                )
                return RugSyncResult("created", rug.id, rug.barcode)

            current_version = await self.history.get_current(rug.id, RUG_SOURCE)
            self._raise_on_source_timestamp_conflict(
                rug=rug,
                request=request,
                current_fingerprint=(
                    current_version.fingerprint if current_version is not None else None
                ),
                incoming_fingerprint=fingerprint,
            )
            if current_version is not None and current_version.fingerprint == fingerprint:
                return RugSyncResult("unchanged", rug.id, rug.barcode)

            old_data = (
                current_version.payload
                if current_version is not None
                else self._current_rug_snapshot(rug)
            )
            if current_version is not None:
                current_version.valid_to = observed_at
                await self.session.flush()

            self._update_rug(rug, request)
            self.history.add(
                self._new_history(rug.id, version_payload, fingerprint, observed_at)
            )
            await self._sync_photos(rug.id, normalized_photos, observed_at)
            await self._sync_locations(rug.id, normalized_locations, observed_at)
            self.audit.add(
                self._audit_event(
                    rug.id,
                    action="updated",
                    old_data=old_data,
                    new_data=version_payload,
                )
            )
            return RugSyncResult("updated", rug.id, rug.barcode)

    @staticmethod
    def _raise_on_source_timestamp_conflict(
        *,
        rug: Rug,
        request: RugImportRequest,
        current_fingerprint: str | None,
        incoming_fingerprint: str,
    ) -> None:
        current_timestamp = rug.source_updated_at
        incoming_timestamp = request.source_updated_at
        if current_timestamp is None or incoming_timestamp is None:
            return
        if incoming_timestamp < current_timestamp:
            raise RugSyncConflictError(
                code="stale_snapshot",
                message="Входящий snapshot старше текущего состояния ковра",
                barcode=rug.barcode,
                current_source_updated_at=current_timestamp,
                incoming_source_updated_at=incoming_timestamp,
            )
        if (
            incoming_timestamp == current_timestamp
            and current_fingerprint != incoming_fingerprint
        ):
            raise RugSyncConflictError(
                code="timestamp_conflict",
                message=(
                    "Источник передал разные данные с одинаковым source_updated_at"
                ),
                barcode=rug.barcode,
                current_source_updated_at=current_timestamp,
                incoming_source_updated_at=incoming_timestamp,
            )

    @staticmethod
    def _new_rug(request: RugImportRequest) -> Rug:
        values = {field: getattr(request, field) for field in RUG_MUTABLE_FIELDS}
        values["status"] = request.status.value
        values["category"] = request.category.value
        return Rug(barcode=request.barcode, **values)

    @staticmethod
    def _update_rug(rug: Rug, request: RugImportRequest) -> None:
        for field in RUG_MUTABLE_FIELDS:
            value = getattr(request, field)
            if field == "status":
                value = request.status.value
            elif field == "category":
                value = request.category.value
            setattr(rug, field, value)

    @staticmethod
    def _new_history(
        rug_id: uuid.UUID,
        payload: dict,
        fingerprint: str,
        observed_at: datetime,
    ) -> RugExternalData:
        return RugExternalData(
            rug_id=rug_id,
            source=RUG_SOURCE,
            payload=payload,
            fingerprint=fingerprint,
            valid_from=observed_at,
        )

    async def _sync_photos(
        self,
        rug_id: uuid.UUID,
        incoming_photos: list[tuple[RugPhotoImport, str]],
        observed_at: datetime,
    ) -> None:
        existing = await self.photos.list_current(rug_id)
        existing_by_fingerprint = {photo.fingerprint: photo for photo in existing}
        incoming_fingerprints = {fingerprint for _, fingerprint in incoming_photos}

        for photo in existing:
            if photo.fingerprint not in incoming_fingerprints:
                photo.is_current = False
                photo.valid_to = observed_at

        for incoming, fingerprint in incoming_photos:
            current = existing_by_fingerprint.get(fingerprint)
            if current is not None:
                current.sort_order = incoming.sort_order
                continue
            self.photos.add(
                RugPhoto(
                    rug_id=rug_id,
                    source=incoming.source,
                    external_id=incoming.external_id,
                    local_path=incoming.local_path,
                    original_url=incoming.original_url,
                    sort_order=incoming.sort_order,
                    is_current=True,
                    checksum=incoming.checksum,
                    fingerprint=fingerprint,
                    valid_from=observed_at,
                )
            )

    @staticmethod
    def _deduplicate_photos(
        photos: list[RugPhotoImport],
    ) -> list[tuple[RugPhotoImport, str]]:
        unique: dict[str, RugPhotoImport] = {}
        for photo in photos:
            identity_payload = photo.model_dump(mode="json", exclude={"sort_order"})
            fingerprint = payload_fingerprint(identity_payload)
            current = unique.get(fingerprint)
            if current is None or photo.sort_order < current.sort_order:
                unique[fingerprint] = photo
        return sorted(
            ((photo, fingerprint) for fingerprint, photo in unique.items()),
            key=lambda item: (item[0].sort_order, item[1]),
        )

    @staticmethod
    def _deduplicate_locations(locations: list) -> list[tuple[object, str]]:
        unique: dict[str, object] = {}
        for location in locations:
            fingerprint = payload_fingerprint(location.model_dump(mode="json"))
            unique[fingerprint] = location
        return [(location, fingerprint) for fingerprint, location in sorted(unique.items())]

    async def _sync_locations(
        self,
        rug_id: uuid.UUID,
        incoming_locations: list[tuple[object, str]],
        observed_at: datetime,
    ) -> None:
        existing = list(
            (
                await self.session.scalars(
                    select(RugLocation)
                    .where(RugLocation.rug_id == rug_id, RugLocation.is_current.is_(True))
                    .with_for_update()
                )
            ).all()
        )
        existing_by_fingerprint = {item.fingerprint: item for item in existing}
        incoming_fingerprints = {fingerprint for _, fingerprint in incoming_locations}
        for location in existing:
            if location.fingerprint not in incoming_fingerprints:
                location.is_current = False
                location.valid_to = observed_at
        for incoming, fingerprint in incoming_locations:
            if fingerprint in existing_by_fingerprint:
                continue
            self.session.add(
                RugLocation(
                    rug_id=rug_id,
                    warehouse=incoming.warehouse,
                    cell=incoming.cell,
                    qty=incoming.qty,
                    is_current=True,
                    valid_from=observed_at,
                    fingerprint=fingerprint,
                )
            )

    @staticmethod
    def _build_version_payload(
        request: RugImportRequest,
        photos: list[tuple[RugPhotoImport, str]],
        locations: list[tuple[object, str]],
    ) -> dict:
        rug_data = request.model_dump(
            mode="json", exclude={"photos", "locations", "raw_payload"}, by_alias=False
        )
        photo_data = [photo.model_dump(mode="json") for photo, _ in photos]
        location_data = [location.model_dump(mode="json") for location, _ in locations]
        return to_jsonable(
            {
                "rug": rug_data,
                "photos": photo_data,
                "locations": location_data,
                "raw_payload": request.raw_payload,
            }
        )

    @staticmethod
    def _current_rug_snapshot(rug: Rug) -> dict:
        return to_jsonable(
            {
                "rug": {
                    "barcode": rug.barcode,
                    **{field: getattr(rug, field) for field in RUG_MUTABLE_FIELDS},
                }
            }
        )

    @staticmethod
    def _audit_event(
        rug_id: uuid.UUID,
        *,
        action: str,
        old_data: dict | None,
        new_data: dict,
    ) -> AuditEvent:
        return AuditEvent(
            entity_type="rug",
            entity_id=rug_id,
            action=action,
            actor_type="system",
            actor_id="1c-sync",
            old_data=old_data,
            new_data=new_data,
        )
