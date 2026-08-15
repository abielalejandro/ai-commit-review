from typing import TypedDict


class MsgState(TypedDict, total=False):
    diff: str        # staged diff (sensitive files excluded, capped)
    message: str     # generated Conventional Commits message
