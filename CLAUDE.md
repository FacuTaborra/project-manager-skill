# CLAUDE.md — claude-pm-skill

CLI que le da a Claude Code un tracker (Linear o ClickUp) detrás de un contrato fijo de
subcomandos. Lo usa un equipo, sobre varios tableros, desde varios repos.

## Lo que no se negocia

**Toda mutación pasa por `application/scope.py`.** Ese módulo es el único del repo autorizado a
llamar a los métodos que escriben del port (`create_issue`, `update_issue`, `create_project`,
`create_team`, `create_doc`, `update_doc`, `create_label`).
[tests/test_scope_invariants.py](tests/test_scope_invariants.py) lo verifica por AST y falla el
build si alguien lo rompe.

De ahí cuelgan dos garantías que no se sostienen solas:

- **Nada escribe fuera del scope declarado.** `_authorized_project_id()` es la única función que
  entrega un project id escribible.
- **`--dry-run` es total, no "casi".** No hay un segundo camino a la API que se pueda olvidar.

Si vas a agregar una operación que escribe: el método nuevo va en `ScopeGuard`, llama a
`_authorized_project_id()` primero, y el comando la invoca por `guard.<lo-que-sea>(...)`. Nunca
`provider.<lo-que-sea>(...)` desde un comando.

## Arquitectura

```
cli.py                    argparse; los flags compartidos vienen de parsers padre
  └─ commands/            I/O y serialización JSON, nada de lógica
      └─ application/     servicios: scope (el guard), briefing, search, scope_discovery
          └─ domain/      ports.py (Protocols) + models.py (dataclasses frozen)
              ← infrastructure/providers/{linear,clickup}.py
```

Dependencias runtime: **cero**. Solo stdlib, y así queda. Si algo parece necesitar un paquete,
casi siempre son 40 líneas a mano con mejores mensajes de error.

`commands/_wiring.py` tiene los dos composition roots: `prepare_read()` (sin guard, sin costo de
verificación) y `prepare_write()` (con guard, valida el pin de workspace).

## Configuración

Dos archivos, y ninguno vive en el clone del skill:

- **`<repo>/.pm.toml`** — se commitea. Provider, perfil de credencial, y el `[scope]` que declara
  workspace/space/lists por ID. Su ausencia es la primera barrera: sin él no hay escritura.
  Parser en [src/claude_pm/infrastructure/config_files/pm_file.py](src/claude_pm/infrastructure/config_files/pm_file.py).
- **`~/.claude/pm/credentials.toml`** — nunca se commitea, `chmod 600`. Perfiles nombrados.
  Parser en [src/claude_pm/infrastructure/config_files/credentials_store.py](src/claude_pm/infrastructure/config_files/credentials_store.py).

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

- Nada de comentarios `#` intercalados en medio de una función. Si hace falta explicar el *por qué*,
  va en el docstring. Un comentario breve arriba de una constante o un campo está bien.
- Docstrings que expliquen por qué existe algo, no qué hace la línea de abajo.
- Mensajes de error que digan qué hacer después. Estos archivos se editan a mano.
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

`uv tool install git+https://github.com/FacuTaborra/claude-pm-skill`, y `pm` queda en el PATH.
`SKILL.md` viaja como package data (`force-include` en pyproject) porque instalado así el repo no
existe en disco; `pm install-skill` lo lee con `importlib.resources`.
