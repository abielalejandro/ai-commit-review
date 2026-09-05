import fnmatch
import re
import subprocess
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from reviewer.reviewers import CodeReviewer
from .config import PROMPTS, AppConfig
from .models import Finding
from .state import ReviewState

# ponytail: extension vote hints the language; no LLM call to classify.
LANG_BY_EXT = {
    ".java": "Java", ".cs": ".NET/C#", ".csproj": ".NET/C#", ".vb": ".NET/VB",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".py": "Python", ".go": "Go",
    ".php": "Php"
}

# Never read nor send these to the LLM: secrets and project config of any kind.
# ponytail: curated deny-list of common config/secret files; an exotic project config could still
# slip through — the ceiling. Upgrade path: invert to an allowlist of reviewable code extensions.
_SENSITIVE_PATTERNS = (
    r"\.env(\..+)?$",                    # .env, .env.local, .env.production, ...
    r"\.ya?ml$",                          # ci.yml, docker-compose.yml, ...
    r"\.properties$",                     # Java/Spring
    r"\.toml$", r"\.ini$", r"\.cfg$", r"\.conf$", r"\.config$",
    r"\.lock$",                           # Cargo.lock, Gemfile.lock, yarn.lock, ...
    r"\.gradle(\.kts)?$", r"\.sbt$", r"\.csproj$", r"\.sln$",
    r"settings\.[\w.-]*json$",            # settings.json, settings.local.json, ...
    r"appsettings\.[\w.-]*json$",         # appsettings.json, appsettings.Development.json, ...
    r"launchSettings\.json$",
    r"tsconfig\.[\w.-]*json$", r"jsconfig\.[\w.-]*json$",
    r"\.eslintrc[\w.-]*$", r"\.prettierrc[\w.-]*$", r"\.babelrc[\w.-]*$",
    r"\.editorconfig$", r"\.gitignore$", r"\.gitattributes$", r"\.gitmodules$",
    r"\.npmrc$", r"\.yarnrc[\w.-]*$",
    r"\.gitlab-ci\.ya?ml$", r"\.travis\.ya?ml$",
    r"\.github/",                         # .github/workflows/*, actions, dependabot, ...
    r"(^|/)(Dockerfile|dockerfile)(\..+)?$",
    r"\.dockerignore$",
    r"(^|/)docker-compose[^/]*$", r"(^|/)compose[^/]*\.ya?ml$",
    r"(^|/)Jenkinsfile$", r"(^|/)Makefile$", r"(^|/)CMakeLists\.txt$",
    r"(^|/)pom\.xml$", r"(^|/)AndroidManifest\.xml$",
    r"(^|/)requirements[^/]*\.txt$",
    r"(^|/)Pipfile(\.lock)?$", r"(^|/)poetry\.lock$", r"(^|/)pyproject\.toml$",
    r"(^|/)setup\.cfg$", r"(^|/)tox\.ini$", r"(^|/)\.flake8$",
    r"(^|/)go\.(mod|sum)$",
    r"(^|/)package-lock\.json$", r"(^|/)yarn\.lock$",
    r"(^|/)pnpm-lock\.ya?ml$", r"(^|/)npm-shrinkwrap\.json$",
    r"(^|/)Cargo\.(toml|lock)$",
    r"(^|/)Gemfile(\.lock)?$", r"(^|/)\.ruby-version$",
    r"(^|/)composer\.(json|lock)$", r"(^|/)\.htaccess$",
    r"(^|/)\.terraform/",
    r"(^|/)\.tfvars[\w.-]*$",
    r"(^|/)\.(aws|ssh|kube)/",
    r"(^|/)(secrets|credentials)(\..+)?$",
    r"\.plist$", r"\.xcconfig$", r"\.pbxproj$", r"\.iml$", r"\.classpath$", r"\.project$",
)
SENSITIVE = re.compile("|".join(f"(?:{p})" for p in _SENSITIVE_PATTERNS))
MAX_CHUNK = 20_000                       # chars per review chunk; larger diffs are split, not dropped
SEVERITY = {"low": 0, "medium": 1, "high": 2}
BLOCK_MIN = "medium"                     # block on medium+ in a blocking concern; make it config if teams disagree


def _path_ignored(name: str, patterns: list[str]) -> bool:
    # ponytail: gitignore-lite — trailing "/" = dir prefix, else fnmatch on path or basename. No "!" negation.
    for p in patterns:
        p = p.strip()
        if not p:
            continue
        if p.endswith("/"):
            if name == p[:-1] or name.startswith(p):
                return True
            continue
        if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(name, "**/" + p) or fnmatch.fnmatch(Path(name).name, p):
            return True
    return False


def make_read_diff(cfg: AppConfig):
    def read_diff(state: ReviewState) -> ReviewState:
        names = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        files = [f for f in names if not SENSITIVE.search(f) and not _path_ignored(f, cfg.ignore)]
        if not files:
            return {"diff": ""}
        diff = subprocess.run(
            ["git", "diff", "--cached", "--"] + files,
            capture_output=True, text=True, check=True,
        ).stdout
        if cfg.allow_ignore:
            diff, ignored = filter_ignored(diff)
            for path, snippet, reason in ignored:
                print(f"[ai-review] ignored ({reason}): {path}: {snippet}", file=sys.stderr)
        return {"diff": diff}
    return read_diff


LINE_MARKERS = (
    (re.compile(r"#\s*noqa\b"), "noqa"),
    (re.compile(r"//\s*nolint\b"), "nolint"),
    (re.compile(r"eslint-disable-next-line"), "eslint-disable-next-line"),
    (re.compile(r"eslint-disable-line"), "eslint-disable-line"),
    (re.compile(r"//\s*NOSONAR\b"), "NOSONAR"),
    (re.compile(r"//\s*NOPMD\b"), "NOPMD"),
)
BLOCK_START = (
    (re.compile(r"eslint-disable(?!-next-line|-line)"), "eslint-disable"),
    (re.compile(r"pylint\s*:\s*disable"), "pylint:disable"),
    (re.compile(r"CHECKSTYLE\s*:\s*OFF"), "CHECKSTYLE:OFF"),
)
BLOCK_END = re.compile(r"eslint-enable|pylint\s*:\s*enable|CHECKSTYLE\s*:\s*ON")


def _line_reason(content: str) -> str | None:
    for rx, reason in LINE_MARKERS:
        if rx.search(content):
            return reason
    return None


def _block_start_reason(content: str) -> str | None:
    for rx, reason in BLOCK_START:
        if rx.search(content):
            return reason
    return None


def filter_ignored(diff: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Deterministically strip ignore-marked lines/blocks BEFORE the diff reaches the LLM.

    Reuses standard linter markers (noqa / nolint / eslint-disable / pylint / NOSONAR / NOPMD /
    CHECKSTYLE) so devs don't learn a new convention. Only called when allow_ignore is on.
    """
    ignored: list[tuple[str, str, str]] = []
    out: list[str] = []
    current_file = ""
    in_block = False
    block_reason = ""
    skip_next = False
    for raw in diff.splitlines(keepends=True):
        line = raw.rstrip("\n")
        prefix = line[:1]
        content = line[1:] if prefix in "+- " else line

        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            out.append(raw)
            skip_next = False
            continue
        if line.startswith(("diff --git", "index ", "--- a/", "@@")):
            out.append(raw)
            skip_next = False
            in_block = False
            continue

        if in_block:
            reason = block_reason
            if BLOCK_END.search(content):
                in_block = False
                reason = block_reason + " (end)"
            ignored.append((current_file, content.strip(), reason))
            continue

        if skip_next:
            skip_next = False
            ignored.append((current_file, content.strip(), "eslint-disable-next-line"))
            continue

        lr = _line_reason(content)
        if lr == "eslint-disable-next-line":
            ignored.append((current_file, content.strip(), lr))
            skip_next = True
            continue
        if lr:
            ignored.append((current_file, content.strip(), lr))
            continue

        br = _block_start_reason(content)
        if br:
            in_block = True
            block_reason = br
            ignored.append((current_file, content.strip(), br))
            continue

        out.append(raw)

    return "".join(out), ignored


def chunk_diff(diff: str, max_chars: int) -> list[str]:
    """Split a diff into self-contained chunks, breaking only at file/hunk boundaries.

    Each split chunk re-prepends the file preamble (diff --git / --- / +++) so a split hunk
    keeps its path. A single line larger than max_chars is kept whole (ceiling).
    """
    if len(diff) <= max_chars:
        return [diff] if diff.strip() else []
    chunks: list[str] = []
    acc = ""
    header = ""
    for ln in diff.splitlines(keepends=True):
        if ln.startswith("diff --git "):
            if acc:
                chunks.append(acc)
            header = ln
            acc = ln
        elif ln.startswith(("index ", "--- ", "+++ ")):
            header += ln
            acc += ln
        elif ln.startswith("@@"):
            if acc and acc != header and len(acc) + len(ln) > max_chars:
                chunks.append(acc)
                acc = header + ln
            else:
                acc += ln
        else:
            if acc and acc != header and len(acc) + len(ln) > max_chars:
                chunks.append(acc)
                acc = header + ln
            else:
                acc += ln
    if acc:
        chunks.append(acc)
    return chunks


def make_classify(cfg: AppConfig):
    """Config language/framework wins; else detect by extension."""
    def classify(state: ReviewState) -> ReviewState:
        lang = cfg.language
        if not lang:
            langs: set[str] = set()
            for line in state.get("diff", "").splitlines():
                if line.startswith("+++ b/") or line.startswith("--- a/"):
                    for ext, name in LANG_BY_EXT.items():
                        if line[6:].endswith(ext):
                            langs.add(name)
            lang = ", ".join(sorted(langs)) or "unknown"
        fw = cfg.framework
        return {"language": f"{lang} / {fw}" if fw else lang}
    return classify


def make_reviewer(concern: str, reviewer: CodeReviewer):
    """One impl per enabled concern; all run in parallel after classify(). Fails open.

    Chunks oversized diffs (file/hunk boundaries) and reviews each chunk, so no code is dropped.
    """
    focus = PROMPTS[concern]

    def node(state: ReviewState) -> ReviewState:
        diff = state.get("diff", "").strip()
        if not diff:
            return {"reviews": {concern: []}}
        chunks = chunk_diff(diff, MAX_CHUNK)
        if len(chunks) > 1:
            print(f"[ai-review] {concern}: diff troceado en {len(chunks)} partes", file=sys.stderr)
        system = SystemMessage(
            f"You are a {concern} reviewer. Report ONLY {focus}. "
            f"Languages: {state.get('language', 'unknown')}. "
            "Each finding needs a severity (low/medium/high) and one concrete message. "
            "Return an empty list if there is nothing real to flag."
        )
        findings: list[Finding] = []
        for chunk in chunks:
            try:
                res = reviewer.review([system, HumanMessage(chunk)])
                findings.extend(res.findings)
            except Exception as e:  # fail-open per chunk: one bad chunk must not drop the concern
                print(f"[ai-review] {concern} chunk skipped ({len(chunk)} chars): {e}", file=sys.stderr)
        return {"reviews": {concern: findings}}

    return node


def make_decide(blocking: list[str]):
    """Deterministic verdict: REJECT iff a blocking concern has a finding >= BLOCK_MIN."""
    def decide(state: ReviewState) -> ReviewState:
        reviews = state.get("reviews", {})
        for concern in blocking:
            for f in reviews.get(concern, []):
                if SEVERITY[f.severity] >= SEVERITY[BLOCK_MIN]:
                    return {"verdict": "REJECT", "reason": f"{concern}/{f.severity}: {f.message}"}
        return {"verdict": "PASS", "reason": "No blocking issues."}
    return decide


if __name__ == "__main__":
    # ponytail: offline self-checks for the pure logic (classify + decision policy). No LLM.
    c = make_classify(AppConfig())
    assert c({"diff": "+++ b/App.java\n"})["language"] == "Java"
    assert c({"diff": "+++ b/readme.md\n"})["language"] == "unknown"
    assert make_classify(AppConfig(language="java", framework="spring-boot"))({})["language"] == "java / spring-boot"

    decide = make_decide(["security", "bugs"])
    hi = {"security": [Finding(severity="high", message="hardcoded token")]}
    lo = {"security": [Finding(severity="low", message="nit")]}
    off = {"performance": [Finding(severity="high", message="N+1")]}  # not a blocking concern here
    assert decide({"reviews": hi})["verdict"] == "REJECT"
    assert decide({"reviews": lo})["verdict"] == "PASS"      # low is advisory
    assert decide({"reviews": off})["verdict"] == "PASS"     # non-blocking concern never blocks
    assert decide({"reviews": {}})["verdict"] == "PASS"

    # chunk_diff: split at boundaries, no content lost, small diff untouched
    small = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n+hello\n"
    assert chunk_diff(small, 10_000) == [small]
    big = ("diff --git a/a.py b/a.py\n@@ -1 +1 @@\n" + "+x = 1\n" * 500
           + "diff --git a/b.py b/b.py\n@@ -1 +1 @@\n" + "+y = 2\n" * 500)
    parts = chunk_diff(big, 2000)
    assert len(parts) > 1 and "a.py" in parts[0] and "b.py" in "".join(parts)
    assert "".join(parts).count("+y = 2") == 500

    # filter_ignored: line, block and next-line markers stripped; normal lines kept
    clean, ignored = filter_ignored("+++ b/app.py\n+token = 'x'  # noqa\n+ok = 1\n")
    assert any(r == "noqa" for _, _, r in ignored)
    assert "token" not in clean and "+ok = 1" in clean
    clean, ignored = filter_ignored(
        "+++ b/app.java\n+// CHECKSTYLE:OFF\n+legacy()\n+// CHECKSTYLE:ON\n+keep = 2\n"
    )
    assert "legacy" not in clean and "+keep = 2" in clean
    clean, ignored = filter_ignored("+++ b/app.js\n+// eslint-disable-next-line\n+eval(x)\n+ok = 1\n")
    assert "eval" not in clean and "+ok = 1" in clean

    # SENSITIVE: config/secret files of any kind are excluded; source code is not
    for path in (".env", ".env.local", "application.properties", ".github/workflows/ci.yml",
                 "docker-compose.yml", "web.config", "pyproject.toml", "package-lock.json",
                 "pom.xml", "Dockerfile", "tsconfig.json", "Cargo.lock", "secrets.json"):
        assert SENSITIVE.search(path), path
    for path in ("src/app.py", "main.java", "util.ts", "server.go"):
        assert not SENSITIVE.search(path), path
    print("nodes OK")
