#!/usr/bin/env python3
"""Smoke-test guru-core's local OpenAI-compatible structured-output path."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import NoReturn

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "qwen3.5:9b")
METRIC_IDS = ["baseline", "capacity", "health_constraints", "horizon", "availability"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ready": {"type": "boolean"},
        "missing": {
            "type": "array",
            "items": {"type": "string", "enum": METRIC_IDS},
        },
        "questions": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "metric_id": {"type": "string", "enum": METRIC_IDS},
                    "text": {"type": "string", "minLength": 1},
                    "options": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["metric_id", "text", "options"],
            },
        },
    },
    "required": ["ready", "missing", "questions"],
}

PROMPT = (
    "你是 guru-core 的計畫完整度評估器。\n"
    "使用者目標：我想在 12 週後跑完 5 公里，除此之外沒有提供資料。\n"
    "可用 metric_id 只有 baseline、capacity、health_constraints、horizon、availability。\n"
    "missing 只能放缺少的 metric_id；每個缺項要在 questions 產生一題，"
    "以繁體中文提問，每題恰好三個具體選項。\n"
    "只要 missing 非空，ready 必須是 false；"
    "只有 missing 與 questions 都為空時 ready 才能是 true。\n"
    "只輸出符合提供之 JSON schema 的 JSON，不要 Markdown 或額外說明。"
)


def fail(message: str) -> NoReturn:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        fail("model content is not a JSON object")
    if set(value) != {"ready", "missing", "questions"}:
        fail(f"unexpected top-level keys: {sorted(value)}")
    if not isinstance(value["ready"], bool):
        fail("ready is not boolean")
    if not isinstance(value["missing"], list) or not all(
        isinstance(item, str) for item in value["missing"]
    ):
        fail("missing is not string[]")
    questions = value["questions"]
    if not isinstance(questions, list) or len(questions) > 5:
        fail("questions is not an array of at most five items")
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            fail(f"questions[{index}] is not an object")
        if set(question) != {"metric_id", "text", "options"}:
            fail(f"questions[{index}] has unexpected keys")
        if (
            question["metric_id"] not in METRIC_IDS
            or not isinstance(question["text"], str)
            or not question["text"].strip()
        ):
            fail(f"questions[{index}] has an invalid metric_id or empty text")
        options = question["options"]
        if (
            not isinstance(options, list)
            or len(options) != 3
            or not all(isinstance(option, str) and option.strip() for option in options)
        ):
            fail(f"questions[{index}].options must contain exactly three strings")
    if value["ready"] is False:
        if not questions:
            fail("not-ready output must contain at least one question")
        if set(value["missing"]) != {question["metric_id"] for question in questions}:
            fail("missing metric IDs do not match question metric IDs")
    elif value["missing"] or questions:
        fail("ready output must not contain missing metrics or questions")
    return value


payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": PROMPT}],
    "stream": False,
    "temperature": 0.2,
    "max_tokens": 1200,
    "reasoning_effort": "none",
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "readiness_output",
            "strict": True,
            "schema": SCHEMA,
        },
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
    with urllib.request.urlopen(request, timeout=240) as response:
        envelope = json.load(response)
except urllib.error.HTTPError as error:
    fail(f"HTTP {error.code}: {error.read().decode(errors='replace')}")
except (urllib.error.URLError, TimeoutError) as error:
    fail(f"request failed: {error}")

elapsed = time.monotonic() - started
try:
    content = envelope["choices"][0]["message"]["content"]
    result = validate(json.loads(content))
except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
    fail(f"invalid OpenAI-compatible response: {error}")

usage = envelope.get("usage", {})
print("PASS: Traditional Chinese structured output is valid")
print(f"model={MODEL} elapsed_seconds={elapsed:.2f} usage={json.dumps(usage)}")
print(json.dumps(result, ensure_ascii=False, indent=2))
