"""Pydantic models for the GSRS substance validation payload."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ValidationLink",
    "ValidationMessage",
    "ValidationResponse",
]


class ValidationLink(BaseModel):
    model_config = ConfigDict(extra="allow")

    href: str | None = None
    text: str | None = None


class ValidationMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    discriminator: str | None = Field(
        default=None,
        validation_alias=AliasChoices("_discriminator", "discriminator"),
    )
    message: str | None = Field(
        default=None,
        validation_alias=AliasChoices("message", "text"),
    )
    messageType: str | None = Field(
        default=None,
        validation_alias=AliasChoices("messageType", "type"),
    )
    severity: str | None = None
    property: str | None = Field(
        default=None,
        validation_alias=AliasChoices("property", "propertyName"),
    )
    actionType: str | None = None
    messageId: str | None = None
    suggestedChange: bool | None = None
    appliedChange: bool | None = None
    path: str | None = None
    links: list[ValidationLink] = Field(default_factory=list)


class ValidationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    valid: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("valid", "isValid"),
    )
    messages: list[ValidationMessage] = Field(
        default_factory=list,
        validation_alias=AliasChoices("messages", "validationMessages"),
    )

    @field_validator("messages", mode="before")
    @classmethod
    def _normalize_messages(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            normalized = []
            for item in value:
                if isinstance(item, str):
                    normalized.append({"message": item})
                else:
                    normalized.append(item)
            return normalized
        return value
