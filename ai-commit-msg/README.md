# ai-commit-msg

Genera el mensaje de commit con IA como hook **prepare-commit-msg**, orquestado con
**LangGraph**. Sin dependencia de OpenClaw. Gemelo de `ai-code-review`.

Grafo:
```
read_diff → draft → (mensaje a stdout)
```
`read_diff` toma el diff staged **excluyendo archivos sensibles** (`.env`, `settings.json`,
`.yml/.yaml`, `.properties`) y lo capea a 20k chars. `draft` pide al LLM un mensaje
**Conventional Commits** con salida estructurada (`type`/`scope`/`subject`/`body`) y lo formatea.

## Instalación

```bash
pip install .          # o: pipx install .   /   pip install git+https://github.com/USER/ai-commit-msg
export OPENAI_API_KEY=sk-...
```

Genera el comando `ai-commit-msg`, que imprime el mensaje sugerido a stdout.

## Hook

`scripts/prepare-commit-msg` llama a `ai-commit-msg` y pre-rellena el mensaje.
No hace nada si: hay `-m`/merge/amend, falta la key, o el comando no está instalado.
Instalar en un repo:

```bash
ln -sf "$(pwd)/scripts/prepare-commit-msg" .git/hooks/prepare-commit-msg
```

## Config (env vars)

| Var | Default | Qué es |
|-----|---------|--------|
| `OPENAI_API_KEY` | — | requerido |
| `OPENAI_BASE_URL` | `(OpenAI por defecto)` | endpoint OpenAI-compatible |
| `COMMIT_MODEL` | `gpt-4o-mini` | modelo |
