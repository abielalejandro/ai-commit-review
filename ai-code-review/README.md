# ai-code-review

Revisor de código con IA que corre como hook **pre-commit**, orquestado con **LangGraph**.
Bloquea el commit si el veredicto es `REJECT`.

Grafo (fan-out / fan-in), reviewers según `.ai-review.yml`:
```
read_diff → classify ─┬─ security ─┐
                      ├─ bugs ─────┼→ decide → PASS/REJECT
                      └─ … ────────┘
```
`classify` detecta el/los lenguaje(s) por extensión (sin LLM) y abre a los reviewers
habilitados, que corren **en paralelo**. Cada uno devuelve findings estructurados
(`severity` + `message`) y escribe a `reviews[concern]`; un **reducer** (`merge_reviews`)
los mergea en el fan-in. `decide` es **código puro, determinístico**: REJECT solo si un
concern *bloqueante* trae un finding de severidad ≥ `medium`.

Comportamiento clave:
- **Fail-open** — si el LLM falla (API caída, key inválida) el commit **no se bloquea**; se
  saltea ese reviewer con un warning en stderr.
- **Decisión en código, no en el prompt** — la política de bloqueo la enforcea Python.
- **Diff grande** — se parte por archivo/hunk en trozos y se revisa cada trozo (con warning
  en stderr); nunca se descarta código por tamaño.
- `low` = advisory (avisa, no bloquea, aunque el concern sea bloqueante).

## Instalación

Instala el comando `ai-review` (via `[project.scripts]` del `pyproject.toml`):

```bash
pip install .                                   # desde la carpeta del proyecto
pip install git+https://github.com/USER/ai-code-review   # desde git
pip install -e .                                # editable, para desarrollo
```

Después:

```bash
export DEEPSEEK_API_KEY=sk-...
ai-review        # revisa el diff staged del repo actual
```

Recomendado en venv por repo, o `pipx install .` para tenerlo global aislado.

## Uso como pre-commit

En el repo que querés proteger:

```bash
ln -sf "$(pwd)/../ai-code-review/scripts/pre-commit" .git/hooks/pre-commit
chmod +x ai-code-review/scripts/pre-commit
```

Al hacer `git commit`, se revisa el diff staged. `REJECT` → exit 1 → commit abortado.

## Config por repo (`.ai-review.yml`)

Opcional. Controla qué reviewers corren y cuáles bloquean.

**Cascada** (el de más abajo pisa al de arriba, por clave):
1. defaults built-in (security/bugs/architecture on; security/bugs bloquean)
2. global del usuario → `~/.config/ai-review/config.yml` (respeta `XDG_CONFIG_HOME`)
3. `.ai-review.yml` en la raíz del repo

Así ponés tus preferencias una vez a nivel global y cada repo solo overridea lo que difiere.

```yaml
language: java          # omitir = autodetección por extensión
framework: spring-boot
provider: deepseek
model: deepseek-chat
review:                 # qué corre (en paralelo)
  security: true
  bugs: true
  architecture: true
  performance: false
  style: false           # linter determinístico por lenguaje (opt-in)
blocking:               # cuáles abortan el commit; el resto es advisory
  security: true
  bugs: true
  architecture: false
  performance: false
  style: false

ignore:                 # archivos/dirs que el reviewer nunca analiza (globs tipo .gitignore)
  - "**/*.min.js"
  - "vendor/"
  - "generated/"

allow_ignore: true      # habilita los markers de ignore por línea/bloque (noqa, nolint, ...)

linters:                # qué linter corre por lenguaje (defaults; "none" = deshabilita)
  java: checkstyle
  javascript: eslint
  typescript: eslint
  go: golangci-lint
  python: ruff
  csharp: dotnet-format
```

Un concern `blocking: true` pero `review: false` no bloquea (no corre). Los reviewers
habilitados escriben a `reviews[concern]` y un **reducer** (`merge_reviews`) los junta en
el fan-in — así el nº de ramas paralelas es dinámico.

## Ignorar código

Dos formas de decirle al reviewer "esto no lo mires".

### Por ruta (`ignore`)

Patrones glob estilo `.gitignore` en `.ai-review.yml`. Se suman al filtro de archivos
sensibles — secretos y configuración de cualquier tipo de proyecto (`.env*`, `*.yaml`/`*.yml`,
`*.properties`, `*.toml`, `*.ini`, `settings*.json`, `Dockerfile`, `.github/`, `pom.xml`,
`package-lock.json`, etc.) — que **nunca se leen ni se envían al LLM**.

```yaml
ignore:
  - "vendor/"
  - "**/*.min.js"
  - "migrations/"
  - "**/*_test.go"
```

### Por markers de línea/bloque (`allow_ignore: true`)

Opt-in. Reusa los comentarios estándar de los linters, así no hay que aprender una
convención nueva. El filtrado es **determinístico y ocurre en Python antes de enviar el
diff al LLM**: la línea marcada ni siquiera llega al modelo.

| Marker | Lenguaje | Alcance |
|--------|----------|---------|
| `# noqa` / `# noqa: E501` | Python | línea |
| `# pylint: disable … # pylint: enable` | Python | bloque |
| `//nolint` / `//nolint:golint` | Go | línea |
| `// eslint-disable-line` | JS/TS | línea |
| `// eslint-disable-next-line` | JS/TS | línea + la siguiente |
| `/* eslint-disable */ … /* eslint-enable */` | JS/TS | bloque |
| `// NOSONAR` | Java | línea |
| `// NOPMD` | Java | línea |
| `// CHECKSTYLE:OFF … // CHECKSTYLE:ON` | Java | bloque |

Ejemplos:

```python
token = os.environ["SECRET"]  # noqa          # esta línea no se revisa
```

```go
data, _ := ioutil.ReadFile(path) //nolint     # esta línea no se revisa
```

```java
String password = "hardcoded"; // NOSONAR      # esta línea no se revisa

// CHECKSTYLE:OFF                                # ignora el bloque
legacyMethod();
// CHECKSTYLE:ON
```

```js
// eslint-disable-next-line                      # ignora la línea siguiente
eval(userInput);

/* eslint-disable */                             # ignora el bloque
legacyGlobal = 1;
debugCode();
/* eslint-enable */
```

Comportamiento:
- Un bloque sin su cierre (`enable` / `ON`) se ignora hasta el fin del archivo.
- Todo lo ignorado se loguea en stderr para trazabilidad:

```
[ai-review] ignored (noqa): src/app.py: token = os.environ["SECRET"]
```

> **Advertencia:** esto es un escape hatch intencional. No lo uses para silenciar hallazgos
> reales. `@SuppressWarnings("...")` de Java no se soporta (es una anotación, no un comentario).

## Linter por lenguaje (concern `style`)

Además de los reviewers LLM, podés habilitar un nodo **determinístico** que corre un linter
real por lenguaje sobre los archivos staged (archivo completo). Se configura igual que los
demás concerns: `review.style` lo prende/apaga y `blocking.style` decide si aborta el commit.

```yaml
review:
  style: true
blocking:
  style: false          # advisory por defecto; poné true para que bloqueé en medium+
```

| Lenguaje | Tool default | Alternativas |
|----------|--------------|--------------|
| Java | `checkstyle` | `spotbugs`, `pmd` |
| JavaScript/TypeScript | `eslint` | `biome` |
| Go | `golangci-lint` | `go vet` |
| Python | `ruff` | `pylint` |
| C# | `dotnet-format` | `dotnet build` |

Podés cambiar el tool por lenguaje o deshabilitarlo con `none`:

```yaml
linters:
  java: checkstyle
  javascript: eslint
  typescript: eslint
  go: golangci-lint
  python: ruff
  csharp: none           # deshabilita el lint de C#
```

Comportamiento:
- El linter corre sobre los mismos archivos que revisan los reviewers (los sensibles/ignorados
  quedan fuera).
- **Fail-open**: si el tool no está instalado o falla, se saltea con warning en stderr, igual
  que los reviewers LLM.
- Severidad: `error→high`, `warning→medium`, `info→low` (en Ruff, `F`/pyflakes → high, resto → medium).
- Requiere los tools en el `PATH` (o `eslint` en `node_modules`, vía `npx --no-install`).

### Instalar los linters

#### Java — Checkstyle
Requiere un JRE/JDK ya instalado. El binario `checkstyle`:

```bash
# macOS
brew install checkstyle
# Debian/Ubuntu
sudo apt install checkstyle
```

Sin package manager: descargá `checkstyle-*.jar` de https://github.com/checkstyle/checkstyle/releases
y creá un wrapper `checkstyle` en el `PATH`:

```sh
#!/bin/sh
exec java -jar /ruta/checkstyle-10.x.jar "$@"
```

Corre con la config `sun_checks.xml` por defecto. Verificá: `checkstyle --version`.

#### Go — golangci-lint
Requiere Go instalado:

```bash
go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@latest
```

Asegurate de que `$(go env GOPATH)/bin` esté en tu `PATH`. Verificá: `golangci-lint version`.
Usa `--out-format json` (soportado en v1.43+ y v2).

#### Node.js (JS/TS) — ESLint
El nodo corre `npx --no-install eslint`, así que **ESLint debe ser una dependencia local del
repo que se revisa** (no se descarga solo):

```bash
# en el repo a revisar
npm i -D eslint
# para TypeScript, además:
npm i -D typescript @typescript-eslint/parser @typescript-eslint/eslint-plugin
```

Y necesitás un config, si no, no reporta nada. `eslint.config.js` (flat config):

```js
import ts from "@typescript-eslint/eslint-plugin";

export default [
  { ignores: ["node_modules", "dist"] },
  {
    files: ["**/*.js"],
    languageOptions: { ecmaVersion: "latest" },
    rules: { "no-eval": "error", "no-unused-vars": "warn" },
  },
  {
    files: ["**/*.ts"],
    plugins: { "@typescript-eslint": ts },
    languageOptions: { parser: ts.parser },
    rules: { "@typescript-eslint/no-explicit-any": "warn" },
  },
];
```

#### Python — Ruff
```bash
pip install ruff        # o: pipx install ruff
```
Verificá: `ruff --version`.

#### C# — dotnet format
Requiere el SDK de .NET:
```bash
dotnet format --version
```
Ya viene con el SDK; no hace falta instalar nada extra.

## Config (env vars)

| Var | Default | Qué es |
|-----|---------|--------|
| `OPENAI_API_KEY` | — | requerido para `provider: openai` |
| `DEEPSEEK_API_KEY` | — | requerido para `provider: deepseek` |
| `OPENAI_BASE_URL` | `(OpenAI por defecto)` | cambiá a otro endpoint OpenAI-compatible |
| `GROQ_API_KEY` | — | requerido para `provider: groq` |
| `REVIEW_MODEL` | `gpt-4o-mini` | modelo |

DeepSeek usa la API compatible con OpenAI vía `provider: deepseek`, `model: deepseek-chat`
y `DEEPSEEK_API_KEY`.

## Prueba manual

```bash
git add -p            # stageá algo
python -m reviewer.main
```
