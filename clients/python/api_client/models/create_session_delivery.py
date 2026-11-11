from enum import StrEnum


class CreateSessionDelivery(StrEnum):
    BODY = "body"
    COOKIE = "cookie"

    def __str__(self) -> str:
        return str(self.value)
