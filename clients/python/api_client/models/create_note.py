from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateNote")


@_attrs_define
class CreateNote:
    """
    Attributes:
        title (str):
        body (str | Unset):  Default: ''.
    """

    title: str
    body: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        title = self.title

        body = self.body

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "title": title,
            }
        )
        if body is not UNSET:
            field_dict["body"] = body

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        title = d.pop("title")

        body = d.pop("body", UNSET)

        create_note = cls(
            title=title,
            body=body,
        )

        return create_note
