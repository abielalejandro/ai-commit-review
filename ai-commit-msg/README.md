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
export DEEPSEEK_API_KEY=sk-...
```

Genera el comando `ai-commit-msg`, que imprime el mensaje sugerido a stdout.

## Hook

`scripts/prepare-commit-msg` llama a `ai-commit-msg` y pre-rellena el mensaje.
No hace nada si: hay `-m`/merge/amend, falta la key, o el comando no está instalado.
Instalar en un repo:

```bash
ln -sf "$(pwd)/scripts/prepare-commit-msg" .git/hooks/prepare-commit-msg
```

## Config por repo (`.ai-commig-msg.yml`)

Opcional. Controla qué reviewers corren y cuáles bloquean.

**Cascada** (el de más abajo pisa al de arriba, por clave):
1. global del usuario → `~/.config/ai-commig-msg/config.yml` (respeta `XDG_CONFIG_HOME`)
2. `.ai-commig-msg.yml` en la raíz del repo

Así ponés tus preferencias una vez a nivel global y cada repo solo overridea lo que difiere.

```yaml
provider: deepseek
model: deepseek-chat
```

## Config (env vars)

| Var | Default | Qué es |
|-----|---------|--------|
| `OPENAI_API_KEY` | — | requerido para `provider: openai` |
| `DEEPSEEK_API_KEY` | — | requerido para `provider: deepseek` |
| `GROQ_API_KEY` | — | requerido para `provider: groq` |
| `OPENAI_BASE_URL` | `(OpenAI por defecto)` | endpoint OpenAI-compatible |
| `COMMIT_MODEL` | `gpt-4o-mini` | modelo |
