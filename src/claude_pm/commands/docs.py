"""`create-doc` / `update-doc` — ClickUp Docs via v3 API.

Docs live at workspace level, so there is no list to authorize against; the
workspace pin verified by the guard is what keeps them in the right account.
"""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK, PMError
from ..infrastructure.providers.clickup import ClickUpProvider
from ._helpers import prepare_write, print_result, read_text_arg


def run_create_doc(args: argparse.Namespace) -> int:
    _, provider, guard = prepare_write(args)
    _require_clickup(provider, "create-doc")

    print_result(
        guard.create_doc(title=args.title, content=_content(args)),
        lambda doc: {
            "ok": True,
            "id": doc.id,
            "title": doc.title,
            "url": doc.url,
            "note": "Doc created at workspace level (ClickUp's API cannot attach it to a list).",
        },
    )
    return EXIT_OK


def run_update_doc(args: argparse.Namespace) -> int:
    _, provider, guard = prepare_write(args)
    _require_clickup(provider, "update-doc")

    print_result(
        guard.update_doc(
            doc_id=args.doc_id,
            title=args.title,
            content=_content(args),
            page_id=args.page_id,
        ),
        lambda doc: {"ok": True, "id": doc.id, "title": doc.title, "url": doc.url},
    )
    return EXIT_OK


def _require_clickup(provider: object, command: str) -> None:
    if not isinstance(provider, ClickUpProvider):
        raise PMError(f"{command} is only supported for ClickUp projects.")


def _content(args: argparse.Namespace) -> str | None:
    return read_text_arg(args.content_file or None, "Content")
