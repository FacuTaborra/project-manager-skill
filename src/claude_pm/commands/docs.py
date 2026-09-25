"""`create-doc`, `update-doc` — ClickUp Docs."""

from __future__ import annotations

from argparse import Namespace

from ..dependencies.scope_guard import get_scope_guard
from ..exceptions import EXIT_OK
from ._input import read_text_arg
from ._output import print_write_outcome


def create(args: Namespace) -> int:
    print_write_outcome(
        get_scope_guard(args).create_doc(
            title=args.title, content=read_text_arg(args.content_file, "Content")
        ),
        lambda doc: {
            "ok": True,
            "id": doc.id,
            "title": doc.title,
            "url": doc.url,
            "note": "Doc created at workspace level (ClickUp's API cannot attach it to a list).",
        },
    )
    return EXIT_OK


def update(args: Namespace) -> int:
    print_write_outcome(
        get_scope_guard(args).update_doc(
            doc_id=args.doc_id,
            title=args.title,
            content=read_text_arg(args.content_file, "Content"),
            page_id=args.page_id,
        ),
        lambda doc: {"ok": True, "id": doc.id, "title": doc.title, "url": doc.url},
    )
    return EXIT_OK
