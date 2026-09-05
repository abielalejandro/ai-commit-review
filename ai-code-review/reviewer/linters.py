import json
import re
import subprocess
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path

from reviewer.models import Finding

_SEVERITY = {
    "error": "high", "warning": "medium", "info": "low",
    "high": "high", "medium": "medium", "low": "low",
}


def map_severity(s: str | None) -> str:
    """Normalize a linter's severity token to the Finding severity scale."""
    return _SEVERITY.get((s or "").lower(), "medium")


class Linter(ABC):
    """Deterministic linter that runs a CLI and parses its output into Findings."""

    cmd: tuple[str, ...] = ()

    def run(self, paths: list[str], cwd: Path) -> list[Finding]:
        if not paths:
            return []
        out = subprocess.run([*self.cmd, *paths], capture_output=True, text=True, cwd=cwd).stdout
        return self.parse(out)

    @abstractmethod
    def parse(self, out: str) -> list[Finding]: ...


class CheckstyleLinter(Linter):
    cmd = ("checkstyle", "-f", "xml")

    def parse(self, out: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            root = ET.fromstring(out)
        except ET.ParseError:
            return findings
        for error in root.iter("error"):
            findings.append(Finding(
                severity=map_severity(error.get("severity")),
                message=f"{error.get('source', 'checkstyle')} (line {error.get('line', '?')}): "
                        f"{error.get('message', '').strip()}",
            ))
        return findings


class EslintLinter(Linter):
    cmd = ("npx", "--no-install", "eslint", "--format", "json")

    def parse(self, out: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return findings
        for entry in data:
            file_path = entry.get("filePath", "")
            for m in entry.get("messages", []):
                findings.append(Finding(
                    severity="high" if m.get("severity") == 2 else "medium",
                    message=f"{m.get('ruleId')} ({file_path}:{m.get('line')}): {m.get('message')}",
                ))
        return findings


class GolangciLinter(Linter):
    cmd = ("golangci-lint", "run", "--out-format", "json")

    def parse(self, out: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return findings
        for issue in data.get("Issues", []):
            pos = issue.get("Pos", {})
            findings.append(Finding(
                severity=map_severity(issue.get("Severity")),
                message=f"{issue.get('FromLinter')} ({pos.get('Filename')}:{pos.get('Line')}): "
                        f"{issue.get('Text', '')}",
            ))
        return findings


class RuffLinter(Linter):
    cmd = ("ruff", "check", "--output-format", "json")

    def parse(self, out: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return findings
        for d in data:
            code = d.get("code", "")
            loc = d.get("location", {})
            findings.append(Finding(
                severity="high" if code.startswith("F") else "medium",
                message=f"{code} ({d.get('filename')}:{loc.get('row')}): {d.get('message')}",
            ))
        return findings


_CS_DIAG = re.compile(r"\((\d+),(\d+)\):\s*(error|warning|info)\s+(.+)$")


class DotnetFormatLinter(Linter):
    def run(self, paths: list[str], cwd: Path) -> list[Finding]:
        if not paths:
            return []
        out = subprocess.run(
            ["dotnet", "format", str(cwd), "--verify-no-changes", "--verbosity", "diagnostic"],
            capture_output=True, text=True, cwd=cwd,
        ).stdout
        return self.parse(out)

    def parse(self, out: str) -> list[Finding]:
        findings: list[Finding] = []
        for line in out.splitlines():
            m = _CS_DIAG.search(line)
            if not m:
                continue
            row, _col, kind, rest = m.groups()
            code, _, msg = rest.partition(":")
            findings.append(Finding(
                severity=map_severity(kind),
                message=f"{code.strip()} (line {row}): {msg.strip() or rest.strip()}",
            ))
        return findings


REGISTRY: dict[str, Linter] = {
    "checkstyle": CheckstyleLinter(),
    "eslint": EslintLinter(),
    "golangci-lint": GolangciLinter(),
    "ruff": RuffLinter(),
    "dotnet-format": DotnetFormatLinter(),
}
