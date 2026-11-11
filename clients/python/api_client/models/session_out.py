from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="SessionOut")


@_attrs_define
class SessionOut:
    """
    Attributes:
        expires_at (datetime.datetime):
        token (str | Unset): Present when `delivery` is `body`. Send it as `Authorization: Bearer <token>`.
    """

    expires_at: datetime.datetime
    token: str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        expires_at = self.expires_at.isoformat()

        token = self.token

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "expiresAt": expires_at,
            }
        )
        if token is not UNSET:
            field_dict["token"] = token

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        expires_at = datetime.datetime.fromisoformat(d.pop("expiresAt"))

        token = d.pop("token", UNSET)

        session_out = cls(
            expires_at=expires_at,
            token=token,
        )

        return session_out
