import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from reviewer.models import Finding

_OSV_SEVERITY = {
    "CRITICAL": "high", "HIGH": "high", "MEDIUM": "medium", "LOW": "low",
    "MODERATE": "medium",
}


def _osv_severity(vuln: dict) -> str:
    # ponytail: osv-scanner reports severity in a few shapes; grab the first usable token.
    sev = vuln.get("database_specific", {}).get("severity") or vuln.get("severity")
    if isinstance(sev, list):
        if sev:
            first = sev[0]
            sev = first.get("type") if isinstance(first, dict) else first
        else:
            sev = None
    return _OSV_SEVERITY.get(str(sev or "").upper(), "medium")


class Scanner(ABC):
    """Deterministic repo-level scanner that runs a CLI and parses its output into Findings."""

    cmd: tuple[str, ...] = ()

    def run(self, cwd: Path) -> list[Finding]:
        out = subprocess.run(list(self.cmd), capture_output=True, text=True, cwd=cwd).stdout
        return self.parse(out)

    @abstractmethod
    def parse(self, out: str) -> list[Finding]: ...


class OsvScanner(Scanner):
    cmd = ("osv-scanner", "--format", "json", ".")

    def parse(self, out: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return findings
        for result in data.get("results", []):
            path = result.get("source", {}).get("path", "")
            for pkg in result.get("packages", []):
                p = pkg.get("package", {})
                name = p.get("name", "")
                version = p.get("version", "")
                for vuln in pkg.get("vulnerabilities", []):
                    sev = _osv_severity(vuln)
                    findings.append(Finding(
                        severity=sev,
                        message=f"{name}@{version} ({path}): {vuln.get('id', '?')} — "
                                f"{vuln.get('summary', vuln.get('details', ''))[:120]}",
                    ))
        return findings


class GitleaksScanner(Scanner):
    cmd = ("gitleaks", "git", "--staged", "--report-format", "json", "--report-path", "-")

    def parse(self, out: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return findings
        for leak in data:
            findings.append(Finding(
                severity="high",
                message=f"{leak.get('RuleID', 'secret')} ({leak.get('File')}:{leak.get('StartLine')}): "
                        f"{leak.get('Description', '')}",
            ))
        return findings


SCANNER_REGISTRY: dict[str, Scanner] = {
    "osv-scanner": OsvScanner(),
    "gitleaks": GitleaksScanner(),
}
