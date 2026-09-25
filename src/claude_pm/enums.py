from __future__ import annotations

from enum import StrEnum
from typing import Any

from .exceptions import PMError


class ProviderType(StrEnum):
    LINEAR = "linear"
    CLICKUP = "clickup"

    @classmethod
    def parse(cls, raw: Any, *, where: str = "", error: type[PMError] = PMError) -> ProviderType:
        """`where` prefixes the message with the value's source; `error` lets config parsing
        raise `ConfigError`."""
        try:
            return cls(raw)
        except (ValueError, TypeError):
            supported = ", ".join(member.value for member in cls)
            raise error(f"{where}Unknown provider {raw!r}. Supported: {supported}.") from None
