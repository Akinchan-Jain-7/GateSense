"""Shared schema building blocks: base classes, reusable field types and the page wrapper."""

import re
from typing import Annotated, Any, ClassVar

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)


class ReadModel(BaseModel):
    """Response models are built straight from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)


class WriteModel(BaseModel):
    # Reject unknown fields: a typo like "phone_no" fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UpdateModel(WriteModel):
    """PATCH bodies: every field is optional, and only the fields sent are changed.

    Sending `null` is only allowed for fields listed in `nullable_fields` (e.g. clearing a
    phone number). For anything else, null would break a NOT NULL column, so it's a 422.
    """

    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_null_for_required_columns(self) -> "UpdateModel":
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable_fields:
                raise ValueError(f"'{name}' cannot be null; leave it out to keep the current value")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


Name = Annotated[str, StringConstraints(min_length=2, max_length=120)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=60)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
LowerEmail = Annotated[EmailStr, AfterValidator(str.lower)]

_INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


def _normalize_phone(value: Any) -> Any:
    """Accept '98765 43210', '+91-98765-43210' or '9876543210'; store '+919876543210'."""
    if not isinstance(value, str):
        return value
    digits = re.sub(r"[\s\-()]", "", value)
    if not digits.startswith("+"):
        digits = "+91" + digits.removeprefix("0")
    if not _INDIAN_MOBILE.match(digits):
        raise ValueError("must be a 10-digit Indian mobile number, e.g. 98765 43210")
    return digits


Phone = Annotated[str, BeforeValidator(_normalize_phone)]


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(description="Number of matching records across all pages")
    limit: int
    offset: int
