from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="SessionOut")


@_attrs_define
class SessionOut:
    """
    Attributes:
        token (str):
        expires_at (datetime.datetime):
    """

    token: str
    expires_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        token = self.token

        expires_at = self.expires_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "token": token,
                "expiresAt": expires_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        token = d.pop("token")

        expires_at = datetime.datetime.fromisoformat(d.pop("expiresAt"))

        session_out = cls(
            token=token,
            expires_at=expires_at,
        )

        return session_out
