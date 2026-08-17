import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models.enums import RugCategory, RugStatus

PositiveDimension = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class RugFields(BaseModel):
    barcode: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1)
    status: RugStatus = RugStatus.UNKNOWN
    article: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("article", "sku"),
    )
    country: str | None = Field(default=None, max_length=100)
    composition: str | None = None
    width_cm: PositiveDimension | None = None
    length_cm: PositiveDimension | None = None
    current_location: str | None = Field(default=None, max_length=255)
    retail_price: NonNegativeMoney | None = None
    contractor_price: NonNegativeMoney | None = None
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    source_updated_at: datetime | None = None
    category: RugCategory = RugCategory.RUG
    description: str | None = None
    weight_kg: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)] | None = None
    stock_qty: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)] = Decimal("0")
    stock_unit: str | None = Field(default=None, max_length=50)
    retail_price_unit: str | None = Field(default=None, max_length=50)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("barcode", "name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Значение не должно быть пустым")
        return value

    @field_validator(
        "article",
        "country",
        "composition",
        "current_location",
        "description",
        "stock_unit",
        "retail_price_unit",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("source_updated_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("source_updated_at должен содержать часовой пояс")
        return value


class RugPhotoImport(BaseModel):
    source: str = Field(default="1c", min_length=1, max_length=50)
    external_id: str | None = Field(default=None, max_length=255)
    local_path: str | None = None
    original_url: str | None = None
    sort_order: int = Field(default=0, ge=0)
    checksum: str | None = Field(default=None, max_length=128)
    format: Literal["jpg", "jpeg", "png", "webp", "heic"] | None = None

    @model_validator(mode="after")
    def require_stable_photo_data(self) -> "RugPhotoImport":
        if not any(
            (self.external_id, self.local_path, self.original_url, self.checksum)
        ):
            raise ValueError(
                "Фотография должна иметь external_id, путь, URL или checksum"
            )
        candidates = [self.local_path, self.original_url, self.external_id]
        detected = next(
            (
                value.rsplit(".", 1)[-1].lower().split("?", 1)[0]
                for value in candidates
                if value and "." in value
            ),
            None,
        )
        if self.format is None and detected not in {"jpg", "jpeg", "png", "webp", "heic"}:
            raise ValueError("Для фотографии требуется подтверждённый формат изображения")
        return self


class RugLocationImport(BaseModel):
    warehouse: str = Field(min_length=1, max_length=255)
    cell: str | None = Field(default=None, max_length=255)
    qty: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]

    @field_validator("warehouse")
    @classmethod
    def normalize_warehouse(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Склад не должен быть пустым")
        return normalized

    @field_validator("cell")
    @classmethod
    def normalize_cell(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class RugImportRequest(RugFields):
    photos: list[RugPhotoImport] = Field(default_factory=list)
    locations: list[RugLocationImport] = Field(default_factory=list)
    raw_payload: dict[str, Any]

    @model_validator(mode="after")
    def only_retail_price_is_accepted_from_one_c(self) -> "RugImportRequest":
        if self.contractor_price is not None:
            raise ValueError("Интеграция 1С принимает только розничную цену")
        return self


class RugPhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    external_id: str | None
    local_path: str | None
    original_url: str | None
    sort_order: int
    is_current: bool
    checksum: str | None
    created_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None


class RugRead(RugFields):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class RugHistoryInfo(BaseModel):
    version_count: int
    has_history: bool
    current_fingerprint: str | None
    first_version_at: datetime | None
    last_version_at: datetime | None


class RugDetail(RugRead):
    photos: list[RugPhotoRead]
    history: RugHistoryInfo


class RugListResponse(BaseModel):
    items: list[RugRead]
    page: int
    page_size: int
    total: int


class RugUpsertResponse(BaseModel):
    result: Literal["created", "updated", "unchanged"]
    rug_id: uuid.UUID
    barcode: str
