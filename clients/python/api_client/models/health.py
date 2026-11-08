from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="Health")


@_attrs_define
class Health:
    """
    Attributes:
        status (Literal['ok'] | Unset):  Default: 'ok'.
    """

    status: Literal["ok"] | Unset = "ok"

    def to_dict(self) -> dict[str, Any]:
        status = self.status

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        status = cast(Literal["ok"] | Unset, d.pop("status", UNSET))
        if status != "ok" and not isinstance(status, Unset):
            raise ValueError(f"status must match const 'ok', got '{status}'")

        health = cls(
            status=status,
        )

        return health
