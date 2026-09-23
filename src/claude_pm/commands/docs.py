"""`create-doc` / `update-doc` — ClickUp Docs via v3 API.

Which trackers support docs, and why there is no list to authorize, is the
guard's business (`ScopeGuard.create_doc`); this module only does I/O.
"""

from __future__ import annotations

import argparse

from ..exceptions import EXIT_OK
from ._input import read_text_arg
from ._output import print_write_outcome
from ._wiring import prepare_write


def run_create_doc(args: argparse.Namespace) -> int:
    _, _, guard = prepare_write(args)

    print_write_outcome(
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
    _, _, guard = prepare_write(args)

    print_write_outcome(
        guard.update_doc(
            doc_id=args.doc_id,
            title=args.title,
            content=_content(args),
            page_id=args.page_id,
        ),
        lambda doc: {"ok": True, "id": doc.id, "title": doc.title, "url": doc.url},
    )
    return EXIT_OK


def _content(args: argparse.Namespace) -> str | None:
    return read_text_arg(args.content_file, "Content")
