from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..models.create_session_delivery import CreateSessionDelivery
from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateSession")


@_attrs_define
class CreateSession:
    """
    Attributes:
        email (str):
        password (str):
        delivery (CreateSessionDelivery | Unset): `body` returns the token. `cookie` sets it in an httpOnly `__Host-
            session` cookie instead, for a browser app on the same origin as the API. Default: CreateSessionDelivery.BODY.
    """

    email: str
    password: str
    delivery: CreateSessionDelivery | Unset = CreateSessionDelivery.BODY

    def to_dict(self) -> dict[str, Any]:
        email = self.email

        password = self.password

        delivery: str | Unset = UNSET
        if not isinstance(self.delivery, Unset):
            delivery = self.delivery.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "email": email,
                "password": password,
            }
        )
        if delivery is not UNSET:
            field_dict["delivery"] = delivery

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        email = d.pop("email")

        password = d.pop("password")

        _delivery = d.pop("delivery", UNSET)
        delivery: CreateSessionDelivery | Unset
        if isinstance(_delivery, Unset):
            delivery = UNSET
        else:
            delivery = CreateSessionDelivery(_delivery)

        create_session = cls(
            email=email,
            password=password,
            delivery=delivery,
        )

        return create_session
