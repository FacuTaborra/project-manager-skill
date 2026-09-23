"""What stands between this machine and a working `/pm`.

Setup is a short chain and every link has one obvious next command. Rather than
leaving a reader — usually Claude — to infer the order from the README, the tool
reports the next step itself. `doctor`, `creds add`, `creds import`, `init` and
`install-skill` all print it, so wherever you land you are told where to go.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..credentials import credentials_path, list_profiles
from ..exceptions import PMError
from ..infrastructure.repo_detect import PM_FILE_NAME, find_pm_file, find_repo_root

SKILL_DIR = Path.home() / ".claude" / "skills" / "pm"
SKILL_FILE = SKILL_DIR / "SKILL.md"


@dataclass(frozen=True)
class Step:
    """One thing to do, with the command that does it."""

    why: str
    command: str
    hint: str = ""

    def render(self) -> str:
        lines = ["", f"  ▸ Próximo paso: {self.why}", f"      {self.command}"]
        lines.extend(f"    {line}" for line in self.hint.splitlines() if line)
        return "\n".join(lines)


READY = Step(
    why="ya está todo listo — abrí Claude Code en este repo y usá /pm",
    command="/pm",
)


def next_step(start: Path | None = None) -> Step:
    """The first unmet requirement, or READY."""
    for check in (_skill_step, _credentials_step):
        if step := check():
            return step
    return _repo_step(start) or READY


def _skill_step() -> Step | None:
    from ..infrastructure.permissions import missing_permissions

    if not SKILL_FILE.is_file():
        return Step(
            why="instalar la skill para que Claude Code la vea",
            command="pm install-skill --yes",
        )
    if missing_permissions():
        return Step(
            why="registrar los permisos para que Claude no pregunte en cada llamada",
            command="pm install-skill --yes",
        )
    return None


def _credentials_step() -> Step | None:
    try:
        profiles = list_profiles()
    except PMError:
        return Step(
            why=f"arreglar {credentials_path()}, que no se puede leer",
            command="pm creds list",
        )
    if not profiles:
        return Step(
            why="guardar tu token",
            command="pm creds add --name <nombre> --provider clickup --token pk_xxx",
            hint=(
                "ClickUp → Settings → Apps → API Token.\n"
                "Para Linear: https://linear.app/settings/api (Read + Write).\n"
                "Si venías de la versión anterior: pm creds import"
            ),
        )
    return None


def _repo_step(start: Path | None) -> Step | None:
    if find_pm_file(start) is not None:
        return None
    if find_repo_root(start) is None:
        return Step(
            why="entrar a un repo git — el binding al tablero vive en su raíz",
            command="cd <tu-repo> && pm init",
        )
    return Step(
        why=f"decirle a este repo a qué tablero escribe ({PM_FILE_NAME})",
        command=f"pm init{_profile_flag()}",
        hint="Te lista los tableros que ve tu token para que elijas. Commiteá el resultado.",
    )


def _profile_flag() -> str:
    """Name the profile only when the provider cannot be inferred from the credentials."""
    try:
        profiles = list_profiles()
    except PMError:
        return ""
    if len({p.provider for p in profiles}) <= 1:
        return ""
    names = " | ".join(p.name for p in profiles)
    return f" --profile <{names}>"
