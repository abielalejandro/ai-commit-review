import re
import subprocess
import sys

from langchain_core.messages import HumanMessage, SystemMessage
from .reviewers import CodeReviewer
from .models import CommitMessage
from .state import MsgState

# Same sensitive-file exclusion as the original hooks: never send these to the LLM.
SENSITIVE = re.compile(r"(\.env|settings\.json|\.ya?ml|\.properties)$")
MAX_DIFF = 20_000


def read_diff(state: MsgState) -> MsgState:
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


def format_message(cm: CommitMessage) -> str:
    header = f"{cm.type}({cm.scope}): {cm.subject}" if cm.scope.strip() else f"{cm.type}: {cm.subject}"
    return header + (f"\n\n{cm.body.strip()}" if cm.body.strip() else "")



def make_reviewer(reviewer: CodeReviewer):
    def node(state: MsgState) -> MsgState:
        diff = state.get("diff", "").strip()
        if not diff:
            return {"message": ""}
        try:
            messages = [
                SystemMessage(
                    "Write a Conventional Commits message for this staged diff. "
                    "Imperative subject, <=72 chars, no trailing period. "
                    "Add a body only if it explains a non-obvious WHY."
                ),
                HumanMessage(diff),
            ]
            cm = reviewer.review(messages)
            return {"message": format_message(cm)}
        except Exception as e:  # fail-open: never break the commit over an AI/infra hiccup
            print(f"[ai-commit-msg] skipped: {e}", file=sys.stderr)
            return {"message": ""}

    return node
if __name__ == "__main__":
    # ponytail: offline self-check for the pure formatting logic. No LLM.
    a = CommitMessage(type="feat", scope="auth", subject="add token refresh", body="")
    assert format_message(a) == "feat(auth): add token refresh", format_message(a)
    b = CommitMessage(type="fix", scope="", subject="handle null user", body="crashed on logout\nwhen session expired")
    assert format_message(b) == "fix: handle null user\n\ncrashed on logout\nwhen session expired", format_message(b)
    print("nodes OK")
