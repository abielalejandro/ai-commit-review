import sys

from .graph import build_graph


def main() -> int:
    # Prints the suggested message to stdout; the hook writes it into the commit file.
    msg = build_graph().invoke({}).get("message", "").strip()
    if msg:
        print(msg)
    return 0   # fail-open: no message -> hook keeps the default


if __name__ == "__main__":
    sys.exit(main())
