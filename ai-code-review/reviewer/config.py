import os
from pathlib import Path
from pydantic import BaseModel, Field
import yaml

class BlockingOptions(BaseModel):
    security: bool = True
    bugs: bool = True
    architecture: bool = True
    performance: bool = True
    style: bool = False
    maintainability: bool = False
    testing: bool = False
    best_practices: bool = False
    dependencies: bool = False
    secrets: bool = False

class ReviewOptions(BaseModel):
    security: bool = True
    bugs: bool = True
    architecture: bool = True
    performance: bool = True
    style: bool = False
    maintainability: bool = False
    testing: bool = False
    best_practices: bool = False
    dependencies: bool = False
    secrets: bool = False

class LinterOptions(BaseModel):
    java: str = "checkstyle"
    javascript: str = "eslint"
    typescript: str = "eslint"
    go: str = "golangci-lint"
    python: str = "ruff"
    csharp: str = "dotnet-format"

class ScannersOptions(BaseModel):
    dependencies: str = "osv-scanner"
    secrets: str = "gitleaks"


class AppConfig(BaseModel):
    language: str | None = None
    framework: str | None = None
    provider: str = "openai"
    model: str | None = None
    review: ReviewOptions = Field(default_factory=ReviewOptions)
    blocking: BlockingOptions = Field(default_factory=BlockingOptions)
    ignore: list[str] = Field(default_factory=list)
    allow_ignore: bool = False
    linters: LinterOptions = Field(default_factory=LinterOptions)
    scanners: ScannersOptions = Field(default_factory=ScannersOptions)

CONCERNS = ("security", "bugs", "architecture", "performance", "maintainability",
            "testing", "best_practices", "style", "dependencies", "secrets")

DEFAULTS = {
    "language": None,
    "framework": None,
    "provider": "openai",
    "model": None,
    "review":   {"security": True, "bugs": True, "architecture": True, "performance": False,
                 "maintainability": False, "testing": False, "best_practices": False,
                 "style": False, "dependencies": False, "secrets": False},
    "blocking": {"security": True, "bugs": True, "architecture": False, "performance": False,
                 "maintainability": False, "testing": False, "best_practices": False,
                 "style": False, "dependencies": False, "secrets": False},
    "ignore": [],
    "allow_ignore": False,
    "linters": {"java": "checkstyle", "javascript": "eslint", "typescript": "eslint",
                "go": "golangci-lint", "python": "ruff", "csharp": "dotnet-format"},
    "scanners": {"dependencies": "osv-scanner", "secrets": "gitleaks"},
}

# What each reviewer hunts for. Keyed by concern.
PROMPTS = {
    "security": "security holes: leaked secrets, injection, missing authz, unsafe deserialization, path traversal",
    "bugs": "logic bugs: null/None, resource leaks, concurrency races, wrong error handling, off-by-one",
    "architecture": "architecture smells: wrong layering, tight coupling, leaky abstractions, misplaced responsibilities",
    "performance": "performance issues: N+1 queries, needless allocation, blocking I/O on hot paths, bad complexity",
    "maintainability": "maintainability issues: long/complex methods, duplication, dead code, poor naming, unclear control flow",
    "testing": "testing gaps: new or changed behavior without tests, weak or brittle tests, missing edge cases, asserts that verify nothing",
    "best_practices": "idiomatic and best-practice violations: deprecated APIs, framework misuse, anti-patterns, non-idiomatic patterns for the language/framework",
}


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
    return Path(base) / "ai-review" / "config.yml"

def load_config() -> AppConfig:
    project_path = Path.cwd() / ".ai-review.yml"   # o .ai-review.yml, pero uno solo
    merged = deep_merge(
        deep_merge(DEFAULTS, read_yaml(global_config_path())),
        read_yaml(project_path),
    )
    return AppConfig.model_validate(merged)


def enabled(cfg: AppConfig) -> list[str]:
    return [c for c in CONCERNS if getattr(cfg.review, c)]


def blocking(cfg: AppConfig) -> list[str]:
    # Only an enabled concern can block.
    return [c for c in enabled(cfg) if getattr(cfg.blocking, c)]

