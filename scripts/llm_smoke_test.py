#!/usr/bin/env python3
"""Smoke-test a local OpenAI-compatible structured-output path.

Sends the hardest of guru-core's five schemas — the Fit Verdict — because it is the one
that carries real invariants: every shape scored, exactly five evidence items, at least one
for and at least one against, and every citation resolving to a dimension that exists.

A provider that satisfies the JSON Schema and still breaks those rules is exactly what the
application's validate-retry-degrade chain exists for, so this script checks both layers and
reports which one failed.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, NoReturn

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "qwen3.5:9b")

CODES = ["S-1", "S-2", "S-3"]
DIMENSIONS = ["work", "learning", "unclassified"]
EVIDENCE_ITEMS = 5

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "minItems": len(CODES),
            "maxItems": len(CODES),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role_model_code", "fit", "verdict", "note", "evidence", "probe"],
                "properties": {
                    "role_model_code": {"type": "string", "enum": CODES},
                    "fit": {
                        "type": "string",
                        "enum": [
                            "strongly_consistent",
                            "partly_consistent",
                            "moderate_gap",
                            "large_gap",
                            "largest_gap",
                            "runs_opposite",
                        ],
                    },
                    "verdict": {"type": "string", "minLength": 1},
                    "note": {"type": "string", "minLength": 1},
                    "evidence": {
                        "type": "array",
                        "minItems": EVIDENCE_ITEMS,
                        "maxItems": EVIDENCE_ITEMS,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["stance", "text", "cites"],
                            "properties": {
                                "stance": {"type": "string", "enum": ["for", "against"]},
                                "text": {"type": "string", "minLength": 1},
                                "cites": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["dimension", "fact"],
                                    "properties": {
                                        "dimension": {"type": "string", "enum": DIMENSIONS},
                                        "fact": {"type": "string", "minLength": 1},
                                    },
                                },
                            },
                        },
                    },
                    "probe": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["statement", "cost"],
                        "properties": {
                            "statement": {"type": "string", "minLength": 1},
                            "cost": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        }
    },
}

PROMPT = """You score borrowed life shapes against one person's data. You never choose.

The reports for this person, over 26 weeks:
- work: 62% of tracked time, present every week, longest unbroken run 26 weeks
- learning: 5% of tracked time, one Thursday group, 11 weeks unbroken
- unclassified: 16% of tracked time, roughly 118 hours, fits no named dimension

The shapes to score:
- S-1 The Deep Specialist. Go deep on one thing and be known for it. Cost: switching tracks
  gets expensive as depth grows.
- S-2 The Zero-to-One Builder. Always making something that did not exist. Cost: little
  reaches maturity.
- S-3 The Independent Operator. Set your own hours, cover your own costs. Cost: unstable
  income and all the admin is yours.

Rules, all of which are checked:
1. Score every shape listed above, using its code verbatim.
2. Each verdict carries exactly five evidence items.
3. Each verdict has at least one item with stance "for" and at least one with "against".
   This holds for the best-fitting shape and the worst-fitting one alike.
4. Every cites.dimension is one of: work, learning, unclassified.
5. The probe is one experiment finishable in a quarter, and states its own cost.

Return only JSON matching the provided schema. No Markdown, no explanation.
"""


def fail(message: str) -> NoReturn:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def business_rules(payload: dict[str, Any]) -> list[str]:
    """The same invariants `services/engine/domain/verdict.py` enforces in production."""
    verdicts = payload.get("verdicts", [])
    scored = [item.get("role_model_code") for item in verdicts]
    violations = [f"shape {code!r} was not scored" for code in CODES if code not in scored]
    if len(scored) != len(set(scored)):
        violations.append("a shape was scored more than once")

    for item in verdicts:
        prefix = f"verdict for {item.get('role_model_code')!r}"
        evidence = item.get("evidence", [])
        if len(evidence) != EVIDENCE_ITEMS:
            violations.append(f"{prefix} has {len(evidence)} evidence items, not {EVIDENCE_ITEMS}")
        stances = {entry.get("stance") for entry in evidence}
        if not {"for", "against"} <= stances:
            violations.append(f"{prefix} needs at least one 'for' and one 'against'")
        violations += [
            f"{prefix} cites {entry['cites'].get('dimension')!r}, which has no report"
            for entry in evidence
            if entry.get("cites", {}).get("dimension") not in DIMENSIONS
        ]
        probe = item.get("probe", {})
        if not str(probe.get("cost", "")).strip():
            violations.append(f"{prefix} has a probe with no stated cost")
    return violations


def main() -> None:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 6000,
        "reasoning_effort": "none",
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "fit_verdict_set", "strict": True, "schema": SCHEMA},
        },
    }
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer ollama", "Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=240) as response:  # noqa: S310 - local
            envelope = json.load(response)
    except urllib.error.HTTPError as error:
        fail(f"HTTP {error.code}: {error.read().decode(errors='replace')}")
    except (urllib.error.URLError, TimeoutError) as error:
        fail(f"request failed: {error}")

    elapsed = time.monotonic() - started
    try:
        result = json.loads(envelope["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        fail(f"invalid OpenAI-compatible response: {error}")

    violations = business_rules(result)
    if violations:
        # Well-formed and wrong is the interesting failure: it is why the application
        # validates twice and feeds the violation back rather than trusting the schema.
        print("SCHEMA OK, BUSINESS RULES FAILED", file=sys.stderr)
        for message in violations:
            print(f"  - {message}", file=sys.stderr)
        raise SystemExit(1)

    usage = envelope.get("usage", {})
    print("PASS: structured output is valid, and every invariant holds")
    print(f"model={MODEL} elapsed_seconds={elapsed:.2f} usage={json.dumps(usage)}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
