"""GUI platform contract and adapter abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class GuiAdapterMetadata:
    """Identity and capability metadata for a GUI adapter."""

    name: str
    version: str
    capabilities: tuple[str, ...] = ()


class GuiAdapter(Protocol):
    """Lifecycle contract for GUI adapters."""

    metadata: GuiAdapterMetadata

    def start(self) -> None:
        """Start the adapter lifecycle and block until stopped."""

    def stop(self) -> None:
        """Stop the adapter lifecycle and release resources."""
