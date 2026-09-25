# project-manager-skill

[![CI](https://github.com/FacuTaborra/project-manager-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/FacuTaborra/project-manager-skill/actions/workflows/ci.yml)

Un skill para Claude Code que convierte a Claude en tu Project Manager, conectado a **Linear** o **ClickUp**.

En vez de abrir el tracker, revisar qué hay abierto, pensar qué issues crear y completar formularios — le describís la tarea a Claude y él se encarga.

```
/pm                          → resumen de lo que está abierto, en progreso y bloqueado
/pm "agregar multi-tenant"   → propone un board de issues y los crea al confirmar
```

Cada repo declara en un archivo commiteado a qué tablero escribe, y **el CLI se niega por código a escribir en cualquier otro lado**. Eso es lo que lo hace usable por un equipo con varios tableros a la vez.

---

## Requisitos

- Python 3.10+ no alcanza: **3.11+** (usa `tomllib` de la stdlib). Si instalás con `uv`, no tenés que hacer nada — trae su propio intérprete.
- Cuenta en Linear o ClickUp con permisos para crear issues
- [Claude Code](https://docs.anthropic.com/claude/docs/claude-code)

---

## Instalación

```bash
uv tool install git+https://github.com/FacuTaborra/project-manager-skill@v0.2.0
pm install-skill --yes
pm creds add --name <nombre> --provider clickup --token pk_xxx
cd tu-repo && pm init
```

**Si te perdés en cualquier punto, corré `pm doctor`.** Te dice dónde estás parado y cuál es el comando exacto que sigue:

```
$ pm doctor
project-manager-skill 0.2.0 — doctor
  Python:        3.12.12
  Skill:         ~/.claude/skills/pm/SKILL.md (instalada)
  Credenciales:  ninguna

  ▸ Próximo paso: guardar tu token
      pm creds add --name <nombre> --provider clickup --token pk_xxx
    ClickUp → Settings → Apps → API Token.
    Para Linear: https://linear.app/settings/api (Read + Write).
```

Eso también es lo que hace que le puedas pasar el repo a Claude y decirle "instalalo": corre `doctor`, lee el próximo paso, ejecuta, repite. No tiene que adivinar nada de este README.

Siempre instalás una versión fija (`@vX.Y.Z`), así que un push a `main` no te cambia nada. Las versiones
están en [Releases](https://github.com/FacuTaborra/project-manager-skill/releases). Para actualizar,
reinstalás con el tag nuevo y volvés a copiar el skill:

```bash
uv tool install --force git+https://github.com/FacuTaborra/project-manager-skill@vX.Y.Z
pm install-skill --yes
```

`pm doctor` te muestra qué versión tenés. Si venís del paquete viejo `claude-pm-skill`, corré primero
`uv tool uninstall claude-pm-skill`.

---

## Configuración

Son dos archivos. Los secretos nunca entran al repo.

### 1. Tus credenciales — `~/.claude/pm/credentials.toml`

Un perfil por cuenta, así podés tener varios workspaces de ClickUp conviviendo. No lo edites a mano:

```bash
pm creds add --name 4plus --provider clickup --token pk_xxx
```

```
✓ token válido — autenticado como vos@mail.com
✓ alcanza 2 workspace(s): 4Plus (9013377000), Kendal Salud (9017118322)
✓ perfil '4plus' escrito en ~/.claude/pm/credentials.toml
```

Verifica el token contra la API **antes** de guardarlo, así uno mal copiado falla ahí y no tres comandos después. Y te lista los workspaces que ve, que es justo lo que `pm init` te va a preguntar.

- **ClickUp:** Settings → Apps → API Token (empieza con `pk_`)
- **Linear:** <https://linear.app/settings/api> → Create new API key (Read + Write)

Para que el token no quede en el historial de la shell, pasalo por entorno:

```bash
PM_NEW_TOKEN=pk_xxx pm creds add --name 4plus --provider clickup
```

```bash
pm creds list      # qué perfiles hay (tokens redactados)
```

En Linux/macOS el archivo queda en `chmod 600` solo.

### 2. El tablero de cada repo — `<repo>/.pm.toml`

No lo escribas a mano:

```bash
cd mi-repo
pm init
```

En una terminal, `pm init` levanta un wizard y te va preguntando: token (si todavía no tenés ninguno), workspace, y a qué lista escribe este repo.

```
$ pm init

¿Qué workspace?
  1) Urbs Data          90171079544
  2) Hemisphere Brands  90131828277
> 1

¿A qué lista(s) escribe este repo? (números separados por coma, o 'todos')
  1) 4plus                  901713796084
  2) Cahpsa-Melvin          901713794559
  3) Hemisphere-Automation  901713947493
> 1
```

El token se lee sin eco, así que no queda en el scrollback.

Cuando lo corre un script o un agente —sin terminal— no pregunta nada: si falta decidir algo, sale con exit 1 listando las opciones y el flag a pasar (`--workspace-id`, `--space-id`, `--list-id`, `--profile`). `--no-input` fuerza ese modo.

El resultado se ve así:

```toml
version  = 1
provider = "clickup"
profile  = "4plus"

[scope]
workspace_id   = "9013377000"
workspace_name = "Hemisphere"
space_id       = "90130521234"
space_name     = "4plus"
lists = [
  { id = "901305678901", name = "modulo-energia" },
]

[defaults]
labels = ["alerts-api"]
```

**Commiteá ese archivo.** Es el punto: todo el equipo hereda el mismo binding y nadie más tiene que configurar nada.

Los `*_name` no resuelven nada — mandan los IDs. Están para que los errores digan "modulo-energia" en vez de un número, y para detectar si alguien renombró el tablero.

---

## Las barreras

Ninguna depende de que el modelo se porte bien.

| Barrera | Qué impide |
|---|---|
| **Scope lock** | Toda escritura valida su destino contra `[scope]`. Un `--project-id` de otro tablero aborta con exit 4. |
| **Verificación de pertenencia** | `update-issue` lee la task antes de tocarla: si vive en otra lista, aborta. |
| **Pin de workspace** | Si el perfil está atado a otro workspace, falla antes de llamar a la API. Si el token no alcanza el tablero, la API lo rechaza y el error dice qué perfil y qué hacer. `pm doctor` lo verifica explícitamente. |
| **`--dry-run`** | Muestra el destino resuelto por nombre y el payload exacto, sin tocar la API. |
| **Cambios de estructura apagados** | `create-project` y `create-team` requieren `--allow-structural-changes`, y están fuera del contrato del skill. |

```bash
pm create-issue --title "prueba" --description "x" --dry-run
```
```json
{
  "dry_run": true,
  "action": "create-issue",
  "destination": "Hemisphere → 4plus → modulo-energia",
  "payload": { "title": "prueba", "labels": ["alerts-api"] }
}
```

---

## Uso

Abrí Claude Code en cualquier repo con `.pm.toml` y usá `/pm`:

```
/pm
```
→ briefing de issues abiertos.

```
/pm agreguemos un sistema de notificaciones por email
```
→ Claude propone un board, pedís confirmación, y los crea.

---

## Comandos

### Setup

```bash
pm doctor                          # dónde estás parado y qué comando sigue
pm install-skill --yes             # instala SKILL.md + permisos
pm creds add --name N --provider P --token T
pm creds list                      # perfiles (tokens redactados)
pm init                            # escribe .pm.toml en este repo
```

Si venías de una versión anterior: `~/.cache/claude-pm/` ya no se usa y se puede borrar.

### Issues

```bash
pm briefing
pm get-issue --id <id>
pm search "query"
pm create-issue --title "..." --description "..." --state Backlog --priority 2
pm update-issue --id <id> --state complete
```

Todo comando que escribe acepta `--dry-run`.

### Lookups

```bash
pm list-teams                      # spaces disponibles
pm list-projects                   # listas, cada una marcada in_scope
pm list-states
pm list-labels                     # tags del space (ClickUp) o labels (Linear)
pm resolve-user email@example.com
```

---

## Dos repos, un tablero

`alerts-api` y `energy-manage-api` pueden escribir los dos en `modulo-energia`: cada uno declara su
`[defaults] labels`, y toda issue sale etiquetada con el repo que la creó sin que nadie se acuerde
de pasar `--label`.

---

## Para CI

```bash
export PM_TOKEN=pk_xxx
```

`PM_TOKEN` saltea el archivo de credenciales. Las variables `LINEAR_API_KEY` / `CLICKUP_API_KEY`
**no** se leen a propósito: tomar un token del directorio donde uno está parado es justo lo que
este diseño elimina.
