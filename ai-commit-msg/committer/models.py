import os
from functools import lru_cache
from typing import Literal
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class CommitMessage(BaseModel):
    type: Literal["feat", "fix", "refactor", "docs", "test", "chore",
                  "perf", "build", "ci", "style"] = Field(description="Conventional Commits type")
    scope: str = Field(default="", description="Optional short area, no spaces (e.g. auth, api)")
    subject: str = Field(description="Imperative summary, <=72 chars, no trailing period")
    body: str = Field(default="", description="Optional: the WHY, only if it adds real context")