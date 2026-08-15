from typing import Annotated, Literal, TypedDict


def merge_reviews(a: dict, b: dict) -> dict:
    # Reducer: parallel reviewers each write reviews[concern]; merge without clobber.
    return {**a, **b}


class ReviewState(TypedDict, total=False):
    diff: str                                            # staged diff (capped)
    language: str                                        # classify() hint for each reviewer
    reviews: Annotated[dict[str, list], merge_reviews]   # concern -> list[Finding], parallel-merged
    verdict: Literal["PASS", "REJECT"]
    reason: str                                          # one-line justification
    llm: str