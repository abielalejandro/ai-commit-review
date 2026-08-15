from committer.nodes import make_reviewer
from langgraph.graph import END, START, StateGraph
from functools import partial
from .config import load_config
from .nodes import make_reviewer, read_diff
from .state import MsgState
from .factory import create_reviewer

def build_graph(cfg: dict | None = None):
    cfg = cfg or load_config()
    reviewer = create_reviewer(cfg)
    g = StateGraph(MsgState)
    g.add_node("read_diff", read_diff)
    g.add_node("draft", make_reviewer(reviewer))
    g.add_edge(START, "read_diff")
    g.add_edge("read_diff", "draft")
    g.add_edge("draft", END)
    return g.compile()
