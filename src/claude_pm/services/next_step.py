"""What stands between this machine and a working `/pm`.

Setup is a short chain and every link has one obvious next command. Rather than
leaving a reader — usually Claude — to infer the order from the README, the tool
reports the next step itself. `doctor`, `creds add`, `init` and
`install-skill` all print it, so wherever you land you are told where to go.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import PM_FILE_NAME, SKILL_FILE, credentials_path
from ..exceptions import PMError
from ..repositories.claude_settings_repository import missing_permissions
from ..repositories.credentials_repository import list_profiles
from ..repositories.git_repo import find_pm_file, find_repo_root


@dataclass(frozen=True)
class Step:
    """One thing to do, with the command that does it."""

    why: str
    command: str
    hint: str = ""

    def render(self) -> str:
        lines = ["", f"  ▸ Next step: {self.why}", f"      {self.command}"]
        lines.extend(f"    {line}" for line in self.hint.splitlines() if line)
        return "\n".join(lines)


READY = Step(
    why="everything is set — open Claude Code in this repo and use /pm",
    command="/pm",
)


def next_step(start: Path | None = None) -> Step:
    """The first unmet requirement, or READY."""
    for check in (_skill_step, _credentials_step):
        if step := check():
            return step
    return _repo_step(start) or READY


def _skill_step() -> Step | None:
    if not SKILL_FILE.is_file():
        return Step(
            why="install the skill so Claude Code can see it",
            command="pm install-skill --yes",
        )
    if missing_permissions():
        return Step(
            why="register the permissions so Claude doesn't ask on every call",
            command="pm install-skill --yes",
        )
    return None


def _credentials_step() -> Step | None:
    try:
        profiles = list_profiles()
    except PMError:
        return Step(
            why=f"fix {credentials_path()}, which cannot be read",
            command="pm creds list",
        )
    if not profiles:
        return Step(
            why="save your token",
            command="pm creds add --name <name> --provider clickup --token pk_xxx",
            hint=(
                "ClickUp → Settings → Apps → API Token.\n"
                "For Linear: https://linear.app/settings/api (Read + Write)."
            ),
        )
    return None


def _repo_step(start: Path | None) -> Step | None:
    if find_pm_file(start) is not None:
        return None
    if find_repo_root(start) is None:
        return Step(
            why="enter a git repo — the board binding lives at its root",
            command="cd <your-repo> && pm init",
        )
    return Step(
        why=f"tell this repo which board it writes to ({PM_FILE_NAME})",
        command=f"pm init{_profile_flag()}",
        hint="Lists the boards your token can see so you can pick. Commit the result.",
    )


def _profile_flag() -> str:
    """Name the profile only when the provider cannot be inferred from the credentials."""
    try:
        profiles = list_profiles()
    except PMError:
        return ""
    if len({p.provider_type for p in profiles}) <= 1:
        return ""
    names = " | ".join(p.name for p in profiles)
    return f" --profile <{names}>"
