"""Argparse dispatch + main entry point.

Shared flags come from parent parsers rather than the root parser: with
subparsers, a flag declared on the root is overwritten by the subparser's own
default in the same Namespace. So it is `pm create-issue --dry-run`, never
`pm --dry-run create-issue`.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from ._stdio import force_utf8_stdio
from .commands import (
    briefing,
    create_issue,
    creds,
    docs,
    doctor,
    get_issue,
    init,
    install_skill,
    lists,
    search,
    setup,
    update_issue,
)
from .exceptions import EXIT_OK, NeedsChoice, PMError


def _common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repo-name", default=None, help="Override the auto-detected repo name.")
    parser.add_argument(
        "--profile",
        default=None,
        help="Credential profile to use, overriding the one named in .pm.toml.",
    )
    return parser


def _write_parser(common: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False, parents=[common])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the resolved destination and payload without calling the API.",
    )
    return parser


def _structural_parser(write: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False, parents=[write])
    parser.add_argument(
        "--allow-structural-changes",
        action="store_true",
        help="Permit creating spaces/lists. Off by default so the agent cannot reshape the board.",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = _common_parser()
    write = _write_parser(common)
    structural = _structural_parser(write)

    parser = argparse.ArgumentParser(
        prog="pm",
        description="Product Manager CLI for Claude Code, backed by Linear or ClickUp.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # -- setup & diagnostics -------------------------------------------------

    p_init = sub.add_parser("init", parents=[common], help="Write this repo's .pm.toml.")
    p_init.add_argument("--provider", default=None, help="linear | clickup.")
    p_init.add_argument("--workspace-id", default=None)
    p_init.add_argument("--space-id", default=None, help="Skip space discovery.")
    p_init.add_argument("--list-id", action="append", default=None, help="Repeatable.")
    p_init.add_argument(
        "--from-legacy",
        nargs="?",
        const=True,
        default=None,
        help="Pre-fill from the old projects.pm (default: ~/.claude/skills/pm/projects.pm).",
    )
    p_init.add_argument("--force", action="store_true", help="Overwrite an existing .pm.toml.")
    p_init.add_argument("--dry-run", action="store_true", help="Print the TOML, write nothing.")
    p_init.add_argument(
        "--no-input",
        action="store_true",
        help="Never prompt; return exit 2 with a choice payload instead. For non-human callers.",
    )
    p_init.set_defaults(func=init.run)

    p_creds = sub.add_parser("creds", help="Manage credential profiles.")
    creds_sub = p_creds.add_subparsers(dest="creds_cmd", required=True)

    p_creds_add = creds_sub.add_parser(
        "add", help="Verify a token against the API and store it as a named profile."
    )
    p_creds_add.add_argument("--name", default=None, help="Profile name, e.g. 4plus.")
    p_creds_add.add_argument("--provider", default=None, help="linear | clickup.")
    p_creds_add.add_argument(
        "--token",
        default=None,
        help="API token. Omit it and set PM_NEW_TOKEN to keep it out of your shell history.",
    )
    p_creds_add.add_argument(
        "--workspace-id", default=None, help="Pin the profile to one workspace."
    )
    p_creds_add.add_argument("--force", action="store_true", help="Replace an existing profile.")
    p_creds_add.add_argument("--dry-run", action="store_true", help="Verify but do not write.")
    p_creds_add.add_argument(
        "--no-input",
        action="store_true",
        help="Never prompt; fail or return a choice payload instead. For non-human callers.",
    )
    p_creds_add.set_defaults(func=creds.run_add)

    p_creds_list = creds_sub.add_parser("list", help="List profiles (tokens redacted).")
    p_creds_list.set_defaults(func=creds.run_list)

    p_creds_import = creds_sub.add_parser(
        "import", help="Import tokens from the legacy ~/.claude/secrets/*.env files."
    )
    p_creds_import.add_argument("--dry-run", action="store_true")
    p_creds_import.set_defaults(func=creds.run_import)

    p_install = sub.add_parser(
        "install-skill", help="Install SKILL.md into ~/.claude/skills/pm and register permissions."
    )
    p_install.add_argument(
        "--yes", action="store_true", help="Accept the Claude Code permission changes."
    )
    p_install.add_argument("--skip-permissions", action="store_true", help="Install SKILL.md only.")
    p_install.add_argument("--dry-run", action="store_true", help="Show what would change.")
    p_install.set_defaults(func=install_skill.run)

    p_doctor = sub.add_parser("doctor", parents=[common], help="Diagnose configuration.")
    p_doctor.set_defaults(func=doctor.run)

    p_setup = sub.add_parser(
        "setup", parents=[common], help="Verify the declared scope and refresh the cache."
    )
    p_setup.add_argument("--force", action="store_true", help="Refresh even if the cache is fresh.")
    p_setup.set_defaults(func=setup.run)

    # -- reads ---------------------------------------------------------------

    p_brief = sub.add_parser(
        "briefing", parents=[common], help="Open issues grouped by state, plus vault context."
    )
    p_brief.set_defaults(func=briefing.run)

    p_search = sub.add_parser(
        "search", parents=[common], help="Search issues for duplicate detection."
    )
    p_search.add_argument("query")
    p_search.add_argument(
        "--global-search",
        action="store_true",
        help="Search the whole workspace instead of this repo's list.",
    )
    p_search.set_defaults(func=search.run)

    p_get = sub.add_parser(
        "get-issue", parents=[common], help="Fetch a single issue, including its description."
    )
    p_get.add_argument("--id", required=True, help="Issue identifier (e.g. FAC-12 or a task id).")
    p_get.set_defaults(func=get_issue.run)

    p_teams = sub.add_parser("list-teams", parents=[common], help="List spaces/teams.")
    p_teams.set_defaults(func=lists.run_list_teams)

    p_projects = sub.add_parser("list-projects", parents=[common], help="List lists/projects.")
    p_projects.add_argument("--team-id", default=None, help="Space/team id; defaults to the scope.")
    p_projects.set_defaults(func=lists.run_list_projects)

    p_states = sub.add_parser("list-states", parents=[common], help="List workflow states.")
    p_states.set_defaults(func=lists.run_list_states)

    p_labels = sub.add_parser("list-labels", parents=[common], help="List labels/tags.")
    p_labels.set_defaults(func=lists.run_list_labels)

    p_user = sub.add_parser("resolve-user", parents=[common], help="Resolve a user id by email.")
    p_user.add_argument("email")
    p_user.set_defaults(func=lists.run_resolve_user)

    # -- writes --------------------------------------------------------------

    p_create = sub.add_parser("create-issue", parents=[write], help="Create an issue.")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--description", default=None, help="Description as Markdown.")
    p_create.add_argument(
        "--description-file",
        default=None,
        help="Path to a UTF-8 Markdown file. Overrides --description.",
    )
    p_create.add_argument("--state", default=None, help="State name (Backlog, Todo, ...).")
    p_create.add_argument(
        "--priority",
        type=int,
        default=None,
        help="0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low.",
    )
    p_create.add_argument("--assignee", default=None, help="Email of the member to assign.")
    p_create.add_argument(
        "--label",
        action="append",
        default=None,
        help="Label name (repeatable). Added on top of the repo's default labels.",
    )
    p_create.add_argument(
        "--project-id",
        default=None,
        help="Which list to write to. Required when the repo's scope has several.",
    )
    p_create.set_defaults(func=create_issue.run)

    p_update = sub.add_parser("update-issue", parents=[write], help="Update an existing issue.")
    p_update.add_argument("--id", required=True, help="Issue identifier.")
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--description", default=None)
    p_update.add_argument("--description-file", default=None, help="Overrides --description.")
    p_update.add_argument("--state", default=None, help="State name (e.g. 'In Progress').")
    p_update.add_argument("--priority", type=int, default=None)
    p_update.add_argument("--assignee", default=None, help="Email of the member to assign.")
    p_update.set_defaults(func=update_issue.run)

    p_create_doc = sub.add_parser(
        "create-doc", parents=[write], help="Create a ClickUp Doc (workspace level)."
    )
    p_create_doc.add_argument("--title", required=True)
    p_create_doc.add_argument("--content-file", default=None, help="UTF-8 Markdown file.")
    p_create_doc.set_defaults(func=docs.run_create_doc)

    p_update_doc = sub.add_parser(
        "update-doc", parents=[write], help="Update a ClickUp Doc's title or page content."
    )
    p_update_doc.add_argument("--doc-id", required=True)
    p_update_doc.add_argument("--title", default=None)
    p_update_doc.add_argument("--content-file", default=None)
    p_update_doc.add_argument("--page-id", default=None, help="Omit to append a new page.")
    p_update_doc.set_defaults(func=docs.run_update_doc)

    # -- structural writes, off by default -----------------------------------

    p_create_project = sub.add_parser(
        "create-project", parents=[structural], help="Create a list/project in this repo's space."
    )
    p_create_project.add_argument("name")
    p_create_project.set_defaults(func=lists.run_create_project)

    p_create_team = sub.add_parser(
        "create-team", parents=[structural], help="Create a team (Linear only)."
    )
    p_create_team.add_argument("name")
    p_create_team.set_defaults(func=lists.run_create_team)

    return parser


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        return int(result) if result is not None else EXIT_OK
    except NeedsChoice as e:
        print(json.dumps(e.payload, indent=2, ensure_ascii=False))
        print(str(e), file=sys.stderr)
        return e.exit_code
    except PMError as e:
        print(str(e), file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
