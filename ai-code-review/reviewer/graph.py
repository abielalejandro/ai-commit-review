from langgraph.graph import END, START, StateGraph

from .config import blocking, enabled, load_config
from .factory import create_reviewer
from .nodes import make_classify, make_decide, make_read_diff, make_reviewer
from .state import ReviewState


def build_graph(cfg: dict | None = None):
    cfg = cfg or load_config()
    concerns = enabled(cfg)

    reviewer = create_reviewer(cfg)
    g = StateGraph(ReviewState)
    g.add_node("read_diff", make_read_diff(cfg))
    g.add_node("classify", make_classify(cfg))
    g.add_node("decide", make_decide(blocking(cfg)))

    g.add_edge(START, "read_diff")
    g.add_edge("read_diff", "classify")
    # Fan-out to each enabled reviewer (parallel), fan-in to the deterministic decide node.
    for c in concerns:
        g.add_node(c, make_reviewer(c, reviewer))
        g.add_edge("classify", c)
        g.add_edge(c, "decide")
    if not concerns:
        g.add_edge("classify", "decide")
    g.add_edge("decide", END)
    return g.compile()
