from typing import Literal
from pydantic import BaseModel, Field

class Finding(BaseModel):
    severity: Literal["low", "medium", "high"] = Field(description="How serious the issue is")
    message: str = Field(description="One concrete issue, with the location if visible")


class Findings(BaseModel):
    """Structured output every reviewer returns."""
    findings: list[Finding] = Field(default_factory=list)
