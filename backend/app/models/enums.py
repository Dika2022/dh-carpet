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

