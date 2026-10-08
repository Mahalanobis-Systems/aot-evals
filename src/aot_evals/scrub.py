"""Find secrets and personal data in files that are about to be committed (C6, principle 5).

Secrets block (a case with one fails C6). Personal data warns: it is often legitimate test
data, and a person decides. Neither list is complete; this is a backstop for a human read
(C7), not a substitute for one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "openai_style_key": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    "slack_token": re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    "bearer_token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{24,}"),
    "password_assignment": re.compile(r"(?i)\b(?:password|passwd|secret|api_key|apikey)\b\"?\s*[:=]\s*\"?[^\s\"']{8,}"),
}

_SAFE_EMAIL_DOMAINS = re.compile(r"@(?:[\w.-]+\.)?(?:example\.(?:com|org|net)|test|invalid|localhost)\b", re.I)

PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<![\w.])(?:\+?\d{1,2}[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?![\w.])"),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "card_number": re.compile(r"\b(?:\d[ \-]?){13,19}\b"),
}


@dataclass
class Finding:
    kind: str  # "secret" | "pii"
    pattern: str
    excerpt: str


def _luhn(digits: str) -> bool:
    nums = [int(d) for d in digits if d.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(nums)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact(s: str) -> str:
    return s if len(s) <= 8 else f"{s[:4]}…{s[-2:]}"


def scan(text: str) -> list[Finding]:
    found: list[Finding] = []
    for name, pat in SECRET_PATTERNS.items():
        for m in pat.finditer(text):
            found.append(Finding("secret", name, _redact(m.group(0))))
    for name, pat in PII_PATTERNS.items():
        for m in pat.finditer(text):
            value = m.group(0)
            if name == "email" and _SAFE_EMAIL_DOMAINS.search(value):
                continue
            if name == "card_number" and not _luhn(value):
                continue
            found.append(Finding("pii", name, _redact(value)))
    return found
