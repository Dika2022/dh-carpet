import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import DiscountType, RugEventStatus, RugEventType
from app.schemas.rugs import RugImportRequest

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]


class OneCEventImport(BaseModel):
    barcode: str = Field(min_length=1, max_length=64)
    event_type: Literal["retail_price_change", "sale", "customer_return"]
    event_at: datetime
    price: Money | None = None
    old_price: Money | None = None
    qty: Quantity | None = None
    unit: str | None = Field(default=None, max_length=50)
    counterparty: str | None = Field(default=None, max_length=255)
    source_ref: str = Field(min_length=1, max_length=255)
    source_line_key: str = Field(min_length=1, max_length=255)
    document_number: str | None = Field(default=None, max_length=100)
    posted: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event_at должен содержать часовой пояс")
        return value

    @model_validator(mode="after")
    def validate_business_fields(self) -> "OneCEventImport":
        if self.event_type in {"sale", "customer_return"} and (
            self.price is None or self.qty is None
        ):
            raise ValueError("Для продажи и возврата нужны price и qty")
        if self.event_type == "retail_price_change" and self.price is None:
            raise ValueError("Для розничной цены нужен price")
        return self


class OneCDocumentSnapshot(BaseModel):
    event_type: Literal["sale", "customer_return"]
    source_ref: str = Field(min_length=1, max_length=255)
    posted: bool
    line_keys: list[str] = Field(default_factory=list, max_length=5000)

    @field_validator("line_keys")
    @classmethod
    def unique_nonempty_line_keys(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("line_keys не должны быть пустыми")
        if len(value) != len(set(value)):
            raise ValueError("line_keys должны быть уникальными")
        return value

    @model_validator(mode="after")
    def unposted_snapshot_has_no_lines(self) -> "OneCDocumentSnapshot":
        if not self.posted and self.line_keys:
            raise ValueError("У распроведённого документа line_keys должен быть пустым")
        return self


class OneCBulkImportRequest(BaseModel):
    mode: Literal["initial", "incremental"]
    rugs: list[RugImportRequest] = Field(default_factory=list, max_length=1000)
    events: list[OneCEventImport] = Field(default_factory=list, max_length=5000)
    document_snapshots: list[OneCDocumentSnapshot] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_document_snapshots(self) -> "OneCBulkImportRequest":
        snapshot_ids = [(item.event_type, item.source_ref) for item in self.document_snapshots]
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("Snapshot документа должен встречаться в пакете один раз")
        event_ids = [
            (item.event_type, item.source_ref, item.source_line_key)
            for item in self.events
            if item.event_type in {"sale", "customer_return"}
        ]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Строка документа должна встречаться в пакете один раз")
        for snapshot in self.document_snapshots:
            document_events = [
                event
                for event in self.events
                if event.event_type == snapshot.event_type
                and event.source_ref == snapshot.source_ref
            ]
            event_keys = {event.source_line_key for event in document_events}
            if snapshot.posted and event_keys != set(snapshot.line_keys):
                raise ValueError("events и line_keys полного snapshot документа не совпадают")
            if snapshot.posted and any(not event.posted for event in document_events):
                raise ValueError("Проведённый snapshot должен содержать только posted events")
            if not snapshot.posted and document_events:
                raise ValueError("Распроведённый документ не должен содержать events")
        return self


class SyncItemResult(BaseModel):
    entity_type: str
    source_key: str
    status: Literal["succeeded", "failed"]
    result: str | None = None
    error_code: str | None = None


class SyncRunResponse(BaseModel):
    run_id: uuid.UUID
    status: Literal["completed", "completed_with_errors"]
    total_items: int
    succeeded_items: int
    failed_items: int
    items: list[SyncItemResult]


class LalitaEventCreate(BaseModel):
    rug_id: uuid.UUID
    event_at: datetime
    media_item_id: uuid.UUID
    price: Money | None = None
    start_seconds: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)] | None = None
    end_seconds: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)] | None = None
    discount_type: DiscountType | None = None
    discount_value: Money | None = None
    duration_expression: str | None = Field(default=None, max_length=100)
    page_path: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event_at должен содержать часовой пояс")
        return value

    @model_validator(mode="after")
    def validate_price_or_discount(self) -> "LalitaEventCreate":
        if self.price is None and self.discount_type is None:
            raise ValueError("Нужна цена или скидка")
        if self.discount_type is not None and self.discount_value is None:
            raise ValueError("Для скидки требуется discount_value")
        if self.discount_type in {DiscountType.PERCENT, DiscountType.UP_TO_PERCENT} and (
            self.discount_value is not None and self.discount_value > 100
        ):
            raise ValueError("Процент скидки должен быть в диапазоне 0..100")
        if self.end_seconds is not None and (
            self.start_seconds is None or self.end_seconds < self.start_seconds
        ):
            raise ValueError("end_seconds должен быть не меньше start_seconds")
        return self


class LalitaEventConfirm(BaseModel):
    price: Money | None = None
    actor_id: str = Field(min_length=1, max_length=255)


class LalitaEventReject(BaseModel):
    actor_id: str = Field(min_length=1, max_length=255)


class RugEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rug_id: uuid.UUID
    event_type: str
    source: str
    event_at: datetime
    price: Decimal | None
    old_price: Decimal | None
    currency: str
    qty: Decimal | None
    unit: str | None
    counterparty: str | None
    status: str
    expired: bool
    source_ref: str | None
    media_item_id: uuid.UUID | None
    start_seconds: Decimal | None
    end_seconds: Decimal | None
    discount_type: str | None
    discount_value: Decimal | None
    retail_price_at_event: Decimal | None
    calculated_price: Decimal | None
    valid_until: datetime | None
    page_path: str | None
    created_at: datetime
    updated_at: datetime


class HistoryResponse(BaseModel):
    items: list[RugEventRead]
    total: int
    page: int
    page_size: int


class GraphPoint(BaseModel):
    event_id: uuid.UUID
    at: datetime
    value: Decimal
    status: str
    valid_until: datetime | None = None


class GraphSeries(BaseModel):
    id: Literal["retail_price", "lalita_price", "sale_price"]
    rendering: Literal["step", "offer_period", "line"]
    points: list[GraphPoint]


class GraphResponse(BaseModel):
    date_from: datetime
    date_to: datetime
    series: list[GraphSeries]


class RugLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    warehouse: str
    cell: str | None
    qty: Decimal
    is_current: bool
    valid_from: datetime
    valid_to: datetime | None


class ExternalPhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: str
    article: str
    relative_path: str
    checksum: str
    format: str
    width: int | None
    height: int | None
    is_current: bool
