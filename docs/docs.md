# PM Skill — Por qué tu equipo debería usarla

## El problema

Cuando tenés a Claude Code abierto en un repo, hay dos cosas que hacés todo el tiempo que se vuelven fricción:

1. **Saber qué hay pendiente.** Tenés que abrir el browser, ir a Linear o ClickUp, navegar al proyecto correcto, leer los tickets. Tardás 2 minutos en orientarte.
2. **Crear issues bien escritas.** Cuando planificás una feature, alguien tiene que hacer el trabajo de bajar eso a tickets concretos con descripción, criterios de aceptación, y contexto técnico. Si lo hacés a mano, es lento. Si no lo hacés, los tickets quedan a medias.

La PM Skill le da a Claude contexto directo de tu tracker y le permite crear issues sin que salgas del editor.

---

## Cómo se usa

Abrís Claude Code en cualquier repo del equipo y escribís:

```
/pm
```

Claude lee el estado actual de tu proyecto en Linear (o ClickUp) y te responde algo así:

```
## PM Briefing — alerts-api
📅 2026-05-18

### 🔴 Bloqueado
- ALR-42: Deploy falla en prod por variable de entorno missing

### 🔵 En progreso
- ALR-38: Migración a nuevo schema de alertas
- ALR-39: Rate limiting por tenant

### 📋 Próximos (top 5)
- ALR-40: Endpoint de health check
- ALR-41: Dashboard de métricas
```

En 10 segundos sabés dónde está el proyecto. Sin abrir el browser.

---

Si en cambio querés planificar algo nuevo:

```
/pm agreguemos soporte para webhooks salientes
```

Claude busca duplicados en el tracker, propone un tablero de hasta 8 issues con título, tipo, estado inicial y descripción breve, y **espera tu confirmación antes de crear nada**. Si confirmás, crea todos los tickets en Linear/ClickUp con descripción estructurada (objetivo, criterios de aceptación, contexto técnico).

---

## Por qué no simplemente usar MCP

MCP (Model Context Protocol) es la forma "oficial" de conectar Claude con herramientas externas. Linear y ClickUp tienen sus propios MCP servers. Entonces la pregunta obvia es: ¿por qué no usar eso directamente?

### 1. MCP no tiene memoria entre llamadas

Cada vez que Claude necesita saber tu team ID, project ID, o los estados disponibles, MCP hace una llamada a la API. Si en una sesión necesitás briefing + crear 5 issues, son decenas de llamadas redundantes.

La skill tiene un **cache local**, keyeado por repo + perfil + tablero. Después del primer uso, las llamadas de discovery desaparecen. Es instantáneo.

### 2. MCP no tiene contexto del repo

MCP no sabe en qué repo estás trabajando. Tenés que decirle explícitamente a Claude qué proyecto de Linear corresponde a qué carpeta.

La skill lee el `.pm.toml` commiteado en el repo donde corrés Claude Code. Abrís Claude en `alerts-api/` y ya sabe de qué proyecto hablar — y, más importante, a cuál *no* puede escribir.

### 3. MCP te da acceso crudo, no inteligencia

Con MCP, Claude tiene herramientas para hacer llamadas individuales a la API. Pero decidir cuándo usarlas, en qué orden, y cómo interpretar los resultados queda librado a la creatividad de Claude en cada sesión.

La skill tiene un **contrato estricto**: Claude solo puede ejecutar los subcomandos documentados (`briefing`, `create-issue`, `search`, etc.), en un flujo definido. El comportamiento es predecible y consistente entre sesiones y entre desarrolladores del equipo.

### 4. Multi-provider sin duplicar configuración

Si el equipo usa Linear para eng y ClickUp para producto, podés configurar cada repo con su provider. La skill resuelve el provider correcto automáticamente por repo, usando el mismo `/pm` en todos lados.

Con MCP tendrías que configurar y mantener dos MCP servers separados con sus propias rutas de autenticación.

---

## Qué puede hacer


| Comando                                                     | Qué hace                                             |
| ----------------------------------------------------------- | ---------------------------------------------------- |
| `/pm`                                                       | Briefing: qué está abierto, en progreso, bloqueado   |
| `/pm <descripción de feature>`                              | Propone un tablero de issues y las crea al confirmar |
| "buscá si ya existe un ticket sobre X"                      | Busca duplicados en el tracker                       |
| "asigná ALR-42 a [juan@equipo.com](mailto:juan@equipo.com)" | Actualiza assignee de una issue existente            |
| "pasá ALR-38 a In Review"                                   | Cambia el estado de una issue                        |
| "creá un doc en ClickUp con el ADR de esta decisión"        | Crea documentación directamente en ClickUp           |


---

## Cómo se instala

Una vez por máquina:

```bash
uv tool install git+https://github.com/FacuTaborra/claude-pm-skill
pm install-skill --yes
```

Después, tu token personal va en `~/.claude/pm/credentials.toml` — un perfil por cuenta, así podés tener dos workspaces de ClickUp conviviendo. Cada dev usa su propia key; no hay secretos compartidos.

Y una vez por repo:

```bash
cd mi-repo
pm init      # lista los tableros que ves, elegís, escribe .pm.toml
```

Ese `.pm.toml` **se commitea**. El siguiente que clone el repo no configura nada: ya hereda a qué tablero escribe.

Verificás que todo está bien con `pm doctor`, y actualizás con `uv tool upgrade claude-pm-skill`.

---

## Arquitectura (para los curiosos)

La skill es un CLI de Python puro — sin dependencias externas, solo stdlib. Sigue arquitectura hexagonal: el dominio no sabe nada de HTTP ni de qué tracker estás usando. Agregar un nuevo provider (GitHub Issues, Jira) es implementar un Protocol de ~10 métodos y registrarlo.

El flujo cuando escribís `/pm`:

```
Claude Code
  └── lee SKILL.md (instrucciones para Claude)
       └── Claude ejecuta: pm briefing
            └── CLI lee cache → llama API si hace falta → imprime JSON
                 └── Claude parsea JSON y presenta el briefing en tu idioma
```

Claude nunca improvisa cómo hablar con la API. Solo interpreta el JSON que el CLI le devuelve.

Y cuando escribe, pasa por un único punto de control que valida el destino contra el `[scope]` del repo. No es una convención: hay un test que falla el build si algún módulo intenta escribir por fuera.

---

## Preguntas frecuentes

**¿Funciona si el equipo usa Linear y yo uso ClickUp?**
Sí. El provider se declara por repo en su `.pm.toml`, y cada uno apunta al perfil de credencial que corresponda.

**¿Claude puede escribir en un tablero que no debe?**
No, y esto está garantizado por código, no por instrucciones. Cada repo declara en `.pm.toml` el workspace, space y listas a los que puede escribir; cualquier otra cosa aborta con exit 4 — incluido intentar modificar una task que vive en otro tablero. Tampoco puede crear spaces ni listas: eso requiere un flag explícito que está fuera de su contrato.

**¿Y crear issues sin que yo lo pida?**
El briefing es solo lectura. El plan de issues se muestra primero y se crea después de tu "sí". Si querés verlo antes de confirmar, cualquier comando que escribe acepta `--dry-run`, que te muestra el destino resuelto por nombre y el payload exacto sin tocar la API.

**¿Qué pasa si el proyecto no se llama igual que el repo?**
No importa: el binding es por ID, no por nombre. `pm init` te lista lo que hay y elegís.

**¿Los tickets que crea Claude son buenos?**
Depende del contexto que le des. Si le decís "agreguemos webhooks salientes", va a generar issues razonables. Siempre podés editar la propuesta antes de confirmar.