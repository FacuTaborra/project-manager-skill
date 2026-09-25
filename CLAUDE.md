# CLAUDE.md — project-manager-skill

CLI que le da a Claude Code un tracker (Linear o ClickUp) detrás de un contrato fijo de
subcomandos. Lo usa un equipo, sobre varios tableros, desde varios repos.

## Lo que no se negocia

**Toda mutación pasa por `services/scope_guard.py`.** Ese módulo es el único del repo autorizado a
llamar a los métodos que escriben del port (`create_issue`, `update_issue`, `create_project`,
`create_team`, `create_doc`, `update_doc`, `create_label`).
[tests/test_scope_invariants.py](tests/test_scope_invariants.py) lo verifica por AST y falla el
build si alguien lo rompe.

De ahí cuelgan dos garantías que no se sostienen solas:

- **Nada escribe fuera del scope declarado.** `_authorized_project_id()` es la única función que
  entrega un project id escribible.
- **`--dry-run` es total, no "casi".** No hay un segundo camino a la API que se pueda olvidar.

Si vas a agregar una operación que escribe: el método nuevo va en `ScopeGuard`, llama a
`_authorized_project_id()` primero, y el comando la invoca por `get_scope_guard(args).<lo-que-sea>(...)`.
Nunca `provider.<lo-que-sea>(...)` desde un comando.

## Arquitectura

La misma forma que hemisphere-automations: cada comando pide lo que necesita a `dependencies/` y
el resto se lee de izquierda a derecha.

```
cli.py                  argparse → commands
commands/               = routes: leen args, piden dependencias, imprimen JSON
  issues, docs, board, briefing, init, creds, doctor, install_skill
  _input.py             prompts y flags de archivo  ·  _output.py  JSON y notas a stderr
dependencies/           get_repo_config(args) → get_provider(config) → get_scope_guard(args)
services/               scope_guard (el único que escribe), briefing, search,
                        scope_discovery (lo que decide init), credential, next_step
repositories/           I/O: pm_file, credentials, claude_settings, git_repo
  providers/            base.py (Protocols), factory, http_client, linear, clickup
models/                 repo_config (lo que sale de .pm.toml + credencial), tracker (Issue, Team…)
config.py · enums.py · exceptions.py
```

Dos cadenas y nada más:

- **Lectura:** `get_repo_config` → `get_provider` → provider → JSON.
- **Escritura:** `get_scope_guard` → `ScopeGuard` → `_authorized_project_id` → `DryRun` o provider.

Dependencias runtime: **cero**. Solo stdlib, y así queda. Si algo parece necesitar un paquete,
casi siempre son 40 líneas a mano con mejores mensajes de error.

## Configuración

Dos archivos, y ninguno vive en el clone del skill:

- **`<repo>/.pm.toml`** — se commitea. Provider, perfil de credencial, y el `[scope]` que declara
  workspace/space/lists por ID. Su ausencia es la primera barrera: sin él no hay escritura.
  Parser en [src/claude_pm/repositories/pm_file_repository.py](src/claude_pm/repositories/pm_file_repository.py).
- **`~/.claude/pm/credentials.toml`** — nunca se commitea, `chmod 600`. Perfiles nombrados.
  Parser en [src/claude_pm/repositories/credentials_repository.py](src/claude_pm/repositories/credentials_repository.py).

Las claves desconocidas se **rechazan**, no se ignoran. El formato INI viejo las tragaba en
silencio, y así fue como su campo `label:` estuvo meses sin hacer nada.

Las env vars `LINEAR_API_KEY` / `CLICKUP_API_KEY` **no se leen**. Tomar un token del directorio
donde uno está parado es exactamente lo que este diseño saca. Para CI está `PM_TOKEN`.

## Providers

Ambos implementan el `Protocol` `IssueProvider` estructuralmente (no heredan de nada). Mapeo de
conceptos en ClickUp: Space → "team", List → "project", Task → "issue", Status → "state",
**Tag → "label"**.

En ClickUp las tags no tienen ID propio: la identidad es el nombre, así que `Label.id == Label.name`.
Sigue la convención que el adapter ya usaba para los estados, y hace que la resolución de labels
compartida funcione sin cambios. No renombres `IssueDraft.label_ids`.

`_require_workspace_id()` **nunca** descubre. Recibe el workspace pinneado por constructor y falla
si no lo tiene. Antes devolvía `teams[0]`, o sea que el tablero donde escribías dependía del orden
en que ClickUp devolviera la respuesta.

## Estilo

La referencia es hemisphere-automations: código que se explica solo por los nombres.

- **Sin docstrings por defecto.** Sólo una o dos líneas cuando el *por qué* no sale de los nombres
  (el invariante de `ScopeGuard`, por ejemplo). Nunca una que repita el nombre de la función.
- **Sin docstrings que cuenten historia** ("antes era…", "el formato viejo…"). Eso va en el commit.
- Nada de comentarios `#` en medio de una función ni banners `# -- sección --`. Un comentario breve
  arriba de una constante está bien.
- Sin variables que se usan una sola vez para nombrar un paso intermedio: la expresión directa.
- Inyección por constructor, kwargs en las llamadas, métodos cortos, línea en blanco antes del
  `return` final.
- Números y strings mágicos → constantes de módulo.
- Mensajes de error de una oración que digan qué hacer después. Estos archivos se editan a mano.
- `mypy --strict` pasa. Mantenelo así.

## Tests

```bash
uv pip install -e ".[dev]"
.venv/Scripts/python.exe -m pytest -q      # Windows
python -m pytest -q                        # Unix
ruff check . && ruff format --check . && mypy
```

CI corre los cuatro. Los tests importan como `from src.claude_pm...`, o sea que se corren desde la
raíz del repo (`pythonpath = ["."]` en pyproject).

Al tocar el guard, agregá el caso a [tests/test_scope.py](tests/test_scope.py) — y fijate que el
test afirme que la llamada **no** llegó al provider, no solo que tiró la excepción.

## Distribución

`uv tool install git+https://github.com/FacuTaborra/project-manager-skill@vX.Y.Z`, y `pm` queda en el
PATH. Siempre se instala un tag, nunca `HEAD`: lo que está en `main` no le llega a nadie hasta que sale
un release.
`SKILL.md` viaja como package data (`force-include` en pyproject) porque instalado así el repo no
existe en disco; `pm install-skill` lo lee con `importlib.resources`.

La versión vive en un solo lugar, `__version__` en
[src/claude_pm/\_\_init\_\_.py](src/claude_pm/__init__.py); pyproject la lee de ahí. Para sacar un release:
subís `__version__`, mergeás a main, y pusheás el tag `vX.Y.Z`.
[.github/workflows/release.yml](.github/workflows/release.yml) corre los checks, rechaza el tag si no
coincide con `__version__` y crea el GitHub Release. Semver: patch para fixes, minor para features, major
si cambia el formato de `.pm.toml` o de un subcomando.
