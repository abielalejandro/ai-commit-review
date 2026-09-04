import json
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from functools import cached_property
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from reviewer.config import AppConfig
from reviewer.models import Findings


def _strict_schema() -> str:
    """Findings JSON schema tightened for OpenAI/codex strict mode."""
    schema = Findings.model_json_schema()

    def strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                if "properties" in node:
                    node["required"] = list(node["properties"])
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)

    strict(schema)
    return json.dumps(schema)


class CodeReviewer(ABC):

    @abstractmethod
    def review(
        self,
        messages: list[SystemMessage | HumanMessage]
    ) -> Findings:
        ...


class LlmCodeReviewer(CodeReviewer):
    """Reviewers backed by a langchain BaseChatModel with structured output."""

    @property
    @abstractmethod
    def llm(self) -> BaseChatModel:
        ...

    def review(
        self,
        messages: list[SystemMessage | HumanMessage]
    ) -> Findings:
        return self.llm.with_structured_output(Findings).invoke(messages)


class ClaudeCliCodeReviewer(CodeReviewer):
    """No langchain model: shells out to the `claude` CLI and parses its JSON."""

    def __init__(self, config: AppConfig):
        self.config = config

    def review(
        self,
        messages: list[SystemMessage | HumanMessage]
    ) -> Findings:
        schema = json.dumps(Findings.model_json_schema())
        prompt = "\n\n".join(m.content for m in messages) + (
            f"\n\nReturn ONLY a JSON object matching this schema, no prose, "
            f"no code fences:\n{schema}"
        )
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if self.config.model:
            cmd += ["--model", self.config.model]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        envelope = json.loads(out)  # claude wraps the model output in an envelope
        if envelope.get("is_error"):  # e.g. bad --model returns is_error with exit 0
            raise RuntimeError(f"claude cli: {envelope.get('result')}")
        text = envelope["result"]
        # ponytail: slice first{..last} instead of a JSON parser that tolerates fences
        return Findings.model_validate_json(text[text.find("{"): text.rfind("}") + 1])


class CodexCliCodeReviewer(CodeReviewer):
    """Shells out to the `codex` CLI with a strict output schema."""

    def __init__(self, config: AppConfig):
        self.config = config

    def review(
        self,
        messages: list[SystemMessage | HumanMessage]
    ) -> Findings:
        prompt = "\n\n".join(m.content for m in messages)
        with tempfile.TemporaryDirectory() as d:
            schema_path = Path(d) / "schema.json"
            out_path = Path(d) / "out.json"
            schema_path.write_text(_strict_schema())
            cmd = [
                "codex", "exec",
                "--output-schema", str(schema_path),
                "-o", str(out_path),
                "-s", "read-only",
                "--skip-git-repo-check",
            ]
            if self.config.model:
                cmd += ["-m", self.config.model]
            cmd.append(prompt)
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            return Findings.model_validate_json(out_path.read_text())


class AgyCliCodeReviewer(CodeReviewer):
    """Shells out to the `agy` CLI; its JSON envelope carries structured_output."""

    def __init__(self, config: AppConfig):
        self.config = config

    def review(
        self,
        messages: list[SystemMessage | HumanMessage]
    ) -> Findings:
        prompt = "\n\n".join(m.content for m in messages)
        with tempfile.TemporaryDirectory() as d:
            schema_path = Path(d) / "schema.json"
            schema_path.write_text(_strict_schema())
            cmd = [
                "agy", "-p", prompt,
                "--output-format", "json",
                "--json-schema", str(schema_path),
            ]
            if self.config.model:
                cmd += ["--model", self.config.model]
            out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        envelope = json.loads(out)
        if envelope.get("status") != "SUCCESS":
            raise RuntimeError(f"agy cli: {envelope.get('status')}")
        return Findings.model_validate(envelope["structured_output"])

class AnthropicCodeReviewer(LlmCodeReviewer):
    def __init__(self, config: AppConfig):
        self.config = config

    @cached_property
    def llm(self) -> ChatAnthropic:
        return ChatAnthropic(
            model=self.config.model,
            api_key=os.environ["ANTHROPIC_API_KEY"],
            temperature=0,
        )

class OpenAiCodeCodeReviewer(LlmCodeReviewer):

    def __init__(self, config: AppConfig):
        self.config = config

    @cached_property
    def llm(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.config.model,
            api_key=os.environ["OPENAI_API_KEY"],
            temperature=0,
        )


class DeepSeekCodeReviewer(LlmCodeReviewer):

    def __init__(self, config: AppConfig):
        self.config = config

    @cached_property
    def llm(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.config.model or "deepseek-chat",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
            temperature=0,
        )

class GroqCodeReviewer(LlmCodeReviewer):

    def __init__(self, config: AppConfig):
        self.config = config

    @cached_property
    def llm(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.config.model or "qwen/qwen3.6-27b",
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
            temperature=0,
        )

class GeminiCodeReviewer(LlmCodeReviewer):
    def __init__(self, config: AppConfig):
        self.config = config

    @cached_property
    def llm(self) -> ChatGoogleGenerativeAI:
        return ChatGoogleGenerativeAI(
            model=self.config.model,
            api_key=os.environ["GEMINI_API_KEY"]
        )
