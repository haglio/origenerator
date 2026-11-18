from __future__ import annotations

from origenerator.content import load_content


def shown_name(name: str, *, otherwise: str | None = None) -> str:
    return (load_content().get("display_names") or {}).get(name, name if otherwise is None else otherwise)


OTHER_OR_UNKNOWN = "other/unknown"


def in_parentheses(kind: str = "") -> str:
    return f"({OTHER_OR_UNKNOWN} {kind})" if kind else f"({OTHER_OR_UNKNOWN})"
