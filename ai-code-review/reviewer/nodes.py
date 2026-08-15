import re
import subprocess
import sys

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

SENSITIVE = re.compile(r"(\.env|settings\.json|\.ya?ml|\.properties)$")  # never send these to the LLM
MAX_DIFF = 20_000                       # ponytail: char cap; chunk+map-reduce if repos need bigger
SEVERITY = {"low": 0, "medium": 1, "high": 2}
BLOCK_MIN = "medium"                     # block on medium+ in a blocking concern; make it config if teams disagree


def read_diff(state: ReviewState) -> ReviewState:
    names = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    files = [f for f in names if not SENSITIVE.search(f)]
    if not files:
        return {"diff": ""}
    diff = subprocess.run(
        ["git", "diff", "--cached", "--"] + files,
        capture_output=True, text=True, check=True,
    ).stdout
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n...[diff truncated]..."
    return {"diff": diff}


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
    """One impl per enabled concern; all run in parallel after classify(). Fails open."""
    focus = PROMPTS[concern]

    def node(state: ReviewState) -> ReviewState:
        diff = state.get("diff", "").strip()
        if not diff:
            return {"reviews": {concern: []}}
        try:
            messages = [
                SystemMessage(
                    f"You are a {concern} reviewer. Report ONLY {focus}. "
                    f"Languages: {state.get('language', 'unknown')}. "
                    "Each finding needs a severity (low/medium/high) and one concrete message. "
                    "Return an empty list if there is nothing real to flag."
                ),
                HumanMessage(diff),
            ]
            res = reviewer.review(messages)
            return {"reviews": {concern: res.findings}}
        except Exception as e:  # fail-open: a down API must not block every commit
            print(f"[ai-review] {concern} review skipped: {e}", file=sys.stderr)
            return {"reviews": {concern: []}}

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
    c = make_classify({})
    assert c({"diff": "+++ b/App.java\n"})["language"] == "Java"
    assert c({"diff": "+++ b/readme.md\n"})["language"] == "unknown"
    assert make_classify({"language": "java", "framework": "spring-boot"})({})["language"] == "java / spring-boot"

    decide = make_decide(["security", "bugs"])
    hi = {"security": [Finding(severity="high", message="hardcoded token")]}
    lo = {"security": [Finding(severity="low", message="nit")]}
    off = {"performance": [Finding(severity="high", message="N+1")]}  # not a blocking concern here
    assert decide({"reviews": hi})["verdict"] == "REJECT"
    assert decide({"reviews": lo})["verdict"] == "PASS"      # low is advisory
    assert decide({"reviews": off})["verdict"] == "PASS"     # non-blocking concern never blocks
    assert decide({"reviews": {}})["verdict"] == "PASS"
    print("nodes OK")
