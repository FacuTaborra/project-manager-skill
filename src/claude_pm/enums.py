from __future__ import annotations

from enum import StrEnum
from typing import Any

from .exceptions import PMError


class ProviderType(StrEnum):
    LINEAR = "linear"
    CLICKUP = "clickup"

    @classmethod
    def parse(cls, raw: Any, *, where: str = "", error: type[PMError] = PMError) -> ProviderType:
        """Resolve a provider name, or raise `error` listing the supported ones.

        `where` prefixes the message with the file or table the value came from,
        so a bad `.pm.toml` and a bad `--provider` flag point at different places
        with the same wording. `error` lets config files raise `ConfigError`.
        """
        try:
            return cls(raw)
        except (ValueError, TypeError):
            supported = ", ".join(member.value for member in cls)
            raise error(f"{where}Unknown provider {raw!r}. Supported: {supported}.") from None
