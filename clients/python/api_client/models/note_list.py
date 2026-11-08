from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.note_out import NoteOut
    from ..models.page_meta import PageMeta


T = TypeVar("T", bound="NoteList")


@_attrs_define
class NoteList:
    """
    Attributes:
        data (list[NoteOut]):
        meta (PageMeta):
    """

    data: list[NoteOut]
    meta: PageMeta

    def to_dict(self) -> dict[str, Any]:
        data = []
        for data_item_data in self.data:
            data_item = data_item_data.to_dict()
            data.append(data_item)

        meta = self.meta.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "data": data,
                "meta": meta,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.note_out import NoteOut  # noqa: PLC0415
        from ..models.page_meta import PageMeta  # noqa: PLC0415

        d = dict(src_dict)
        data = []
        _data = d.pop("data")
        for data_item_data in _data:
            data_item = NoteOut.from_dict(data_item_data)

            data.append(data_item)

        meta = PageMeta.from_dict(d.pop("meta"))

        note_list = cls(
            data=data,
            meta=meta,
        )

        return note_list
