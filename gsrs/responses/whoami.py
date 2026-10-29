"""Pydantic models for the GSRS ``api/v1/whoami`` payload."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "WhoAmIGroup",
    "WhoAmIResponse",
    "WhoAmIRole",
    "WhoAmIUser",
]


class WhoAmIUser(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    version: int | None = None
    created: datetime | None = None
    modified: datetime | None = None
    deprecated: bool | None = None
    username: str | None = None
    admin: bool | None = None


class WhoAmIRole(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str | None = None


class WhoAmIGroup(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    id: int | None = None


class WhoAmIResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    version: int | None = None
    created: datetime | None = None
    modified: datetime | None = None
    deprecated: bool | None = None
    active: bool | None = None
    systemAuth: bool | None = None
    key: str | None = None
    identifier: str | None = None
    tokenTimeToExpireMS: int | None = None
    roleQueryOnly: bool | None = None
    computedToken: str | None = None
    properties: list[Any] = Field(default_factory=list)
    user: WhoAmIUser | None = None
    roles: list[WhoAmIRole] = Field(default_factory=list)
    groups: list[WhoAmIGroup] = Field(default_factory=list)
    message: str | None = Field(default="OK")
    status: int | None = Field(default=200)

    @field_validator("roles", mode="before")
    @classmethod
    def _coerce_roles(cls, value: Any) -> Any:
        """Accept GSRS role names as plain strings in addition to role objects."""
        if isinstance(value, list):
            return [
                WhoAmIRole(role=item) if isinstance(item, str) else item
                for item in value
            ]
        return value
