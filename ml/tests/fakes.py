"""A scripted LLM for tests. It finds which probe is being asked from the prompt text."""

from __future__ import annotations

import json
from typing import Any

from maestro.llm import LLMResponse
from maestro.probes import LEVEL_PROBES, PROBES


class FakeLLM:
    model = "fake"

    def __init__(self, answers: dict[str, Any], message: str = "none"):
        self.answers = answers
        self.message = message
        self.calls: list[str] = []
        self.thinks: list[bool | None] = []  # think override per call, aligned with calls

    def _probe_key(self, prompt: str) -> str:
        for probe in LEVEL_PROBES.values():
            if probe.question in prompt:
                return probe.key
        for key, probe in PROBES.items():
            if probe.question.split("{")[0] in prompt:
                return key
        raise AssertionError(f"unknown probe in prompt: {prompt[-200:]}")

    def complete(self, system: str, user: str, schema: dict[str, Any], think: bool | None = None) -> LLMResponse:
        self.thinks.append(think)
        if "\nRule: " in user:  # the generic evaluator
            self.calls.append("generic")
            props = schema["properties"]
            if "conditions" in props:  # decomposed mode: the plan
                base = self.answers["generic_plan"]
            elif props.get("answer", {}).get("type") == "boolean":  # decomposed mode: one condition
                check = self.answers["generic_check"]
                base = check(user) if callable(check) else check
            else:
                base = self.answers["generic"]
            content = {"why": "scripted generic", **base}
            if "na_condition_holds" in schema["properties"]:  # the applicability step
                content.setdefault("na_condition_holds", False)
            return LLMResponse(content=json.dumps(content, ensure_ascii=False), duration_ms=1)
        key = self._probe_key(user)
        self.calls.append(key)
        answer = self.answers.get(key, False)
        message, value = answer if isinstance(answer, tuple) else (self.message, answer)
        allowed = schema["properties"]["message"]["enum"]
        content = {"why": f"scripted {key}", "answer": value, "message": message if message in allowed else "none"}
        return LLMResponse(content=json.dumps(content), duration_ms=1)
