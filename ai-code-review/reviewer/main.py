import sys

from .graph import build_graph


def main() -> int:
    result = build_graph().invoke({})
    for concern, findings in result.get("reviews", {}).items():
        for f in findings:
            print(f"  [{concern}/{f.severity}] {f.message}")
    verdict = result.get("verdict", "PASS")
    print(f"[ai-review] {verdict}: {result.get('reason', '')}")
    return 1 if verdict == "REJECT" else 0


if __name__ == "__main__":
    sys.exit(main())
