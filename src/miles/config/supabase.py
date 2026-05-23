"""Supabase project configuration and playbook references.

The Miles application stores its ``process_playbooks`` in Supabase.
This module provides constants and helpers to resolve playbook metadata
for broker-specific workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Project reference
# ---------------------------------------------------------------------------

SUPABASE_PROJECT_ID = "egpqhzubdeklzstzdmtt"

# ---------------------------------------------------------------------------
# Playbook registry (mirrors the ``process_playbooks`` table rows)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlaybookRef:
    """Lightweight reference to a row in ``process_playbooks``."""

    slug: str
    name: str
    description: str = ""


MARTIN_WINTER_PLAYBOOK = PlaybookRef(
    slug="martin-winter-pof-loi-gate",
    name="Martin Winter POF/LOI Gate",
    description=(
        "Hard gate for all inbound Martin Winter deals. "
        "Requires Proof of Funds and Letter of Intent before "
        "any full details or packages are released."
    ),
)

_PLAYBOOK_REGISTRY: dict[str, PlaybookRef] = {
    MARTIN_WINTER_PLAYBOOK.slug: MARTIN_WINTER_PLAYBOOK,
}


def get_playbook(slug: str) -> Optional[PlaybookRef]:
    """Look up a playbook reference by slug."""
    return _PLAYBOOK_REGISTRY.get(slug)


def list_playbooks() -> list[PlaybookRef]:
    """Return all registered playbook references."""
    return list(_PLAYBOOK_REGISTRY.values())
