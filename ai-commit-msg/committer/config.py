import os
from pathlib import Path
from pydantic import BaseModel
import yaml

class AppConfig(BaseModel):
    language: str | None = None
    framework: str | None = None
    provider: str = "openai"
    model: str | None = None

DEFAULTS = {
    "provider": "openai",
    "model": None,
}

class AppConfig(BaseModel):
    provider: str = "openai"
    model: str | None = None

def deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()

    for key, value in override.items():

        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}

def global_config_path() -> Path:
    base = os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "ai-commit-msg" / "config.yml"

def load_config() -> AppConfig:
    project_path = Path.cwd() / ".ai-commit-msg.yml"
    merged = deep_merge(
        deep_merge(DEFAULTS, read_yaml(global_config_path())),
        read_yaml(project_path),
    )
    return AppConfig.model_validate(merged)



if __name__ == "__main__":
    # ponytail: offline self-check for config cascade + policy logic (no LLM, no network).
    import tempfile

    d = load_config("/nonexistent.yml", global_path="/nonexistent.yml")

    with tempfile.TemporaryDirectory() as t:
        g, l = f"{t}/global.yml", f"{t}/local.yml"
        # global alone: performance turns on, language=go
        gc = load_config("/nonexistent.yml", global_path=g)
    print("config OK")
