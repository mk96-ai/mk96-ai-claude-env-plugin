"""Detection of credentials before anything is written to the repository."""

import re
from dataclasses import dataclass

from .payload import Payload

# Well-known credential formats; each match is a secret on its own.
TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{16,}"),
    re.compile(r"://[^/\s:@]+:[^/\s@]+@"),
)
# `password = "value"` or `"apiKey": "value"` assignments with a literal value.
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key)\w*[\"']?\s*[:=]\s*"
    r"[\"']?([^\s\"'`]{8,})"
)
# Values that point to a secret instead of containing it.
PLACEHOLDER_STARTS = ("$", "{", "<", "%", "process.env", "os.environ")

VISIBLE_CHARACTERS = 4


@dataclass(frozen=True)
class Finding:
    key: str
    path: str
    line: int
    masked: str


def _mask(value: str) -> str:
    return value[:VISIBLE_CHARACTERS] + "…"


def _line_secrets(line: str) -> list[str]:
    secrets = [match.group(0) for pattern in TOKEN_PATTERNS for match in pattern.finditer(line)]
    for match in ASSIGNMENT_PATTERN.finditer(line):
        value = match.group(2)
        if not value.startswith(PLACEHOLDER_STARTS):
            secrets.append(value)
    return secrets


def find_secrets(key: str, payload: Payload) -> list[Finding]:
    """Return every likely secret in the text files of an item, with masked values."""
    findings = []
    for path, data in payload.items():
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            findings += [Finding(key, path, number, _mask(secret)) for secret in _line_secrets(line)]
    return findings
