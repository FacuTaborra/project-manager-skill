"""SetupService — verify the declared scope against the tracker and cache its ids.

Discovery is gone. `.pm.toml` already holds the ids, so this no longer guesses
which board a repo belongs to; it confirms that the declared board still exists
and caches the derived bits (states, labels) that change rarely.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config
from ..domain.ports import IssueProvider
from ..exceptions import PMError
from ..infrastructure.cache import Cache, CacheRepository


@dataclass
class SetupResult:
    cache: Cache
    warnings: list[str] = field(default_factory=list)
    refreshed: bool = False


class SetupService:
    def __init__(
        self, provider: IssueProvider, cache_repo: CacheRepository, config: Config
    ) -> None:
        self.provider = provider
        self.cache_repo = cache_repo
        self.config = config

    def ensure(self, *, force: bool = False) -> Cache:
        return self.verify(force=force).cache

    def verify(self, *, force: bool = False) -> SetupResult:
        cache = self.cache_repo.load()
        if not force and cache.is_valid_for(self.config.fingerprint):
            return SetupResult(cache=cache)

        scope = self.config.scope
        warnings: list[str] = []

        spaces = self.provider.list_teams()
        space = next((s for s in spaces if s.id == scope.space_id), None)
        if space is None:
            available = ", ".join(f"{s.name} ({s.id})" for s in spaces) or "(none)"
            raise PMError(
                f"Space {scope.space_id} declared in {self.config.pm_file.path} does not exist "
                f"in this workspace. Available: {available}. Re-run `pm init --force`."
            )
        if scope.space_name and space.name.lower() != scope.space_name.lower():
            warnings.append(
                f"Space {scope.space_id} is now named {space.name!r}, "
                f"but {self.config.pm_file.path} says {scope.space_name!r}."
            )

        projects = {p.id: p for p in self.provider.list_projects(scope.space_id)}
        resolved: list[dict[str, str]] = []
        for ref in scope.lists:
            project = projects.get(ref.id)
            if project is None:
                available = ", ".join(f"{p.name} ({p.id})" for p in projects.values()) or "(none)"
                raise PMError(
                    f"List {ref.id} ({ref.name or 'unnamed'}) declared in "
                    f"{self.config.pm_file.path} is not in space {space.name}. "
                    f"Available: {available}. Re-run `pm init --force`."
                )
            if ref.name and project.name.lower() != ref.name.lower():
                warnings.append(
                    f"List {ref.id} is now named {project.name!r}, "
                    f"but {self.config.pm_file.path} says {ref.name!r}."
                )
            resolved.append({"id": project.id, "name": project.name})

        states = {s.name: s.id for s in self.provider.list_states(scope.space_id)}
        labels = [
            {"id": lbl.id, "name": lbl.name} for lbl in self.provider.list_labels(scope.space_id)
        ]

        written = self.cache_repo.write(
            space_id=space.id,
            space_name=space.name,
            lists=resolved,
            state_ids=states,
            labels=labels,
        )
        return SetupResult(cache=written, warnings=warnings, refreshed=True)
