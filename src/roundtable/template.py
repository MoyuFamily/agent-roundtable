"""Template library for Roundtable discussions.

Loads JSON template definitions from the templates/ directory and provides
helper functions to list, retrieve, and apply templates when creating
discussions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def list_templates() -> list[dict[str, Any]]:
    """Return a list of available templates (name, description, file)."""
    templates: list[dict[str, Any]] = []
    if not _TEMPLATE_DIR.is_dir():
        return templates
    for p in sorted(_TEMPLATE_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            templates.append({
                "id": p.stem,
                "name": data.get("name", p.stem),
                "description": data.get("description", ""),
            })
        except Exception as exc:
            logger.warning("Failed to load template %s: %s", p, exc)
    return templates


def get_template(template_id: str) -> dict[str, Any] | None:
    """Load a template by its ID (filename stem, e.g. 'product-review').

    Returns the parsed JSON dict or None if not found.
    """
    path = _TEMPLATE_DIR / f"{template_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load template %s: %s", path, exc)
        return None


def apply_template(
    template_id: str,
    *,
    subject: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Apply a template with the given subject, returning discussion params.

    Args:
        template_id: Template identifier (e.g. 'product-review').
        subject: The specific topic to fill into {subject} placeholders.
        overrides: Optional overrides for topic, context, max_rounds, etc.

    Returns:
        A dict with keys: topic, context, participants, max_rounds, speech_order.
        None if the template is not found.
    """
    template = get_template(template_id)
    if template is None:
        return None

    result: dict[str, Any] = {
        "topic": template.get("topic_template", "").replace("{subject}", subject),
        "context": template.get("context_template", "").replace("{subject}", subject),
        "participants": template.get("participants", []),
        "max_rounds": template.get("max_rounds", 3),
        "speech_order": template.get("speech_order", "fixed"),
    }

    if overrides:
        result.update(overrides)

    return result
