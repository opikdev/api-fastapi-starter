from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="PageMeta")


@_attrs_define
class PageMeta:
    """
    Attributes:
        limit (int):
        next_cursor (None | str):
    """

    limit: int
    next_cursor: None | str

    def to_dict(self) -> dict[str, Any]:
        limit = self.limit

        next_cursor: None | str
        next_cursor = self.next_cursor

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "limit": limit,
                "nextCursor": next_cursor,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        limit = d.pop("limit")

        def _parse_next_cursor(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        next_cursor = _parse_next_cursor(d.pop("nextCursor"))

        page_meta = cls(
            limit=limit,
            next_cursor=next_cursor,
        )

        return page_meta
