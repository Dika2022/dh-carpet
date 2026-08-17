from enum import StrEnum


class RugStatus(StrEnum):
    AVAILABLE = "available"
    SOLD = "sold"
    WITHDRAWN = "withdrawn"
    UNKNOWN = "unknown"


class RugMediaLinkSource(StrEnum):
    AI = "ai"
    MANAGER = "manager"
    ADMIN = "admin"
    IMPORT = "import"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class RugCategory(StrEnum):
    RUG = "rug"
    CARPET = "carpet"
    HIDE = "hide"


class RugEventType(StrEnum):
    RETAIL_PRICE_CHANGE = "retail_price_change"
    LALITA_PRICE = "lalita_price"
    SALE = "sale"
    CUSTOMER_RETURN = "customer_return"


class RugEventStatus(StrEnum):
    ACTIVE = "active"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REPLACED = "replaced"


class DiscountType(StrEnum):
    PERCENT = "percent"
    ABSOLUTE = "absolute"
    UP_TO_PERCENT = "up_to_percent"
