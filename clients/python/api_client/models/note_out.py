from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="NoteOut")


@_attrs_define
class NoteOut:
    """
    Attributes:
        id (str):
        title (str):
        body (str):
        version (int):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
    """

    id: str
    title: str
    body: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        title = self.title

        body = self.body

        version = self.version

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "title": title,
                "body": body,
                "version": version,
                "createdAt": created_at,
                "updatedAt": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        title = d.pop("title")

        body = d.pop("body")

        version = d.pop("version")

        created_at = datetime.datetime.fromisoformat(d.pop("createdAt"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updatedAt"))

        note_out = cls(
            id=id,
            title=title,
            body=body,
            version=version,
            created_at=created_at,
            updated_at=updated_at,
        )

        return note_out
