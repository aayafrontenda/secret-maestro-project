"""Deterministic stand-in for the ML service.

Uses a few transcript heuristics so demo output looks plausible, and a stable hash for the
rest, so the same dialog always gets the same verdicts. Never used when ML_PROVIDER=http.
"""

import asyncio
import hashlib
import re

from app.ml.schemas import (
    MLCriterion,
    MLCriterionResult,
    MLEvaluateRequest,
    MLEvaluateResponse,
    MLModelInfo,
    MLRange,
    MLTranscriptMessage,
    MLUsage,
)

GREETINGS = re.compile(
    r"здравств|добрый|привет|сәлем|сәлеметсіз|қайырлы|hello|hi\b|good (morning|afternoon|evening)",
    re.I,
)
FAREWELLS = re.compile(
    r"до свидания|всего доброго|хорошего (дня|вечера)|всего хорошего|обращайтесь|рады помочь"
    r"|сау болыңыз|көріскенше|goodbye|bye|have a (good|nice)|thank you for contacting",
    re.I,
)
IDENTITY_OK = re.compile(
    r"личность клиента подтверждена|жеке басы расталды|identity verified", re.I
)
EMPATHY = re.compile(r"понимаю|сожалею|извин|кешіріңіз|түсінемін|sorry|understand|apolog", re.I)
GRAVE = re.compile(
    r"переведите (мне|на мой)|личн(ый|ого) (номер|счет|счёт)|whatsapp мне|мой номер"
    r"|идиот|дурак|тупой|stupid|idiot",
    re.I,
)


def _canonical(code: str) -> str:
    """c01 / C1 / 01 -> c1, so heuristics match the default checklist whatever the id style."""
    m = re.fullmatch(r"[cC]?0*(\d+)", code.strip())
    return f"c{m.group(1)}" if m else code.strip().lower()


def _stable(seed: str, mod: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % mod


class MockMLClient:
    name = "mock"

    def __init__(self, delay_s: float = 0.0) -> None:
        self._delay_s = delay_s

    async def evaluate(self, request: MLEvaluateRequest) -> MLEvaluateResponse:
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        transcript = request.transcript
        operator_msgs = [m for m in transcript if m.speaker == "operator"]
        results = [
            self._judge(request.conversation_id, c, transcript, operator_msgs)
            for c in request.criteria
        ]
        return MLEvaluateResponse(
            conversation_id=request.conversation_id,
            results=results,
            model=MLModelInfo(provider="mock", name="heuristic-v1"),
            usage=MLUsage(prompt_tokens=0, completion_tokens=0, calls=0, cost_usd=0.0),
        )

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    # --- heuristics -------------------------------------------------------------------------

    def _judge(
        self,
        conversation_id: str,
        c: MLCriterion,
        transcript: list[MLTranscriptMessage],
        operator_msgs: list[MLTranscriptMessage],
    ) -> MLCriterionResult:
        key = _canonical(c.code)
        title = c.title.lower()
        last_index = transcript[-1].index if transcript else 0

        if not operator_msgs:
            if c.is_flag:
                return MLCriterionResult(
                    code=c.code, answer="no", explanation="No operator messages."
                )
            if c.allow_na:
                return MLCriterionResult(
                    code=c.code,
                    answer="na",
                    na_reason="The operator never joined the dialog.",
                    explanation="No operator messages to evaluate.",
                    checked_range=MLRange(from_index=0, to_index=last_index),
                )
            return MLCriterionResult(
                code=c.code,
                answer="no" if c.answer_type == "yes_no" else 0,
                explanation="The operator never joined the dialog.",
                checked_range=MLRange(from_index=0, to_index=last_index),
            )

        first_op = operator_msgs[0]
        last_op = operator_msgs[-1]

        if c.is_flag or "груб" in title or "grave" in title:
            hit = next((m for m in operator_msgs if GRAVE.search(m.text)), None)
            if hit:
                return MLCriterionResult(
                    code=c.code,
                    answer="yes",
                    evidence=[hit.index],
                    explanation="Operator message matches a grave-violation pattern.",
                )
            return MLCriterionResult(
                code=c.code,
                answer="no",
                explanation="No insults, off-platform offers or data leaks found.",
                checked_range=MLRange(from_index=first_op.index, to_index=last_index),
            )

        if key == "c1" or "контакт" in title or "contact" in title:
            ok = bool(GREETINGS.search(first_op.text))
            return MLCriterionResult(
                code=c.code,
                answer="yes" if ok else "no",
                evidence=[first_op.index],
                explanation=(
                    "Operator greeted the client and introduced themselves in the first reply."
                    if ok
                    else "The first operator reply has no greeting."
                ),
            )

        if key == "c3" or "идентиф" in title or "identif" in title:
            verified = next(
                (m for m in transcript if m.speaker == "system" and IDENTITY_OK.search(m.text)),
                None,
            )
            if verified:
                return MLCriterionResult(
                    code=c.code,
                    answer="yes",
                    evidence=[verified.index],
                    explanation="System event confirms the client's identity was verified.",
                )
            if c.allow_na and _stable(conversation_id + key, 3) != 0:
                return MLCriterionResult(
                    code=c.code,
                    answer="na",
                    na_reason="The request did not require identification.",
                    explanation="General question; no protected data or action involved.",
                    checked_range=MLRange(from_index=0, to_index=last_index),
                )
            return MLCriterionResult(
                code=c.code,
                answer="no",
                explanation="Protected data was discussed but identity was never verified.",
                checked_range=MLRange(from_index=first_op.index, to_index=last_index),
            )

        if key == "c5" or "эмпат" in title or "empath" in title:
            hit = next((m for m in operator_msgs if EMPATHY.search(m.text)), None)
            if hit:
                return MLCriterionResult(
                    code=c.code,
                    answer="yes",
                    evidence=[hit.index],
                    explanation="Operator acknowledged the client's concern.",
                )
            return MLCriterionResult(
                code=c.code,
                answer="yes" if _stable(conversation_id + key, 4) else "no",
                evidence=[first_op.index],
                explanation="Tone is polite; no complaint required a specific reaction.",
            )

        if key == "c7" or "заверш" in title or "closing" in title:
            closed_by_client = any(
                m.speaker == "system"
                and re.search(r"клиент покинул|кетті|customer left", m.text, re.I)
                for m in transcript
            )
            if closed_by_client and c.allow_na:
                sys_idx = next(
                    m.index
                    for m in transcript
                    if m.speaker == "system"
                    and re.search(r"клиент покинул|кетті|customer left", m.text, re.I)
                )
                return MLCriterionResult(
                    code=c.code,
                    answer="na",
                    na_reason="The client left before the chat could be closed.",
                    explanation="Chat ended on the client's side.",
                    evidence=[sys_idx],
                )
            ok = bool(FAREWELLS.search(last_op.text))
            return MLCriterionResult(
                code=c.code,
                answer="yes" if ok else "no",
                evidence=[last_op.index],
                explanation=(
                    "Operator summarised/offered help and said goodbye."
                    if ok
                    else "The last operator message has no closing or farewell."
                ),
            )

        if c.answer_type == "scale":
            steps = [int(s["value"]) for s in (c.scale_steps or [])] or [c.scale_max or 0, 0]
            pick = (
                steps[_stable(conversation_id + key, len(steps))] if steps else (c.scale_max or 0)
            )
            mid = operator_msgs[len(operator_msgs) // 2]
            return MLCriterionResult(
                code=c.code,
                answer=pick,
                evidence=[mid.index],
                explanation=f"Heuristic level {pick}/{c.scale_max} based on reply structure.",
            )

        # generic yes/no (e.g. need discovery)
        asks_question = any("?" in m.text for m in operator_msgs[:2])
        if asks_question:
            q = next(m for m in operator_msgs[:2] if "?" in m.text)
            return MLCriterionResult(
                code=c.code,
                answer="yes",
                evidence=[q.index],
                explanation="Operator asked a clarifying question before answering.",
            )
        if c.allow_na:
            return MLCriterionResult(
                code=c.code,
                answer="na",
                na_reason="Enough details were available from the start.",
                explanation="The client's first message already contained all required details.",
                evidence=[transcript[0].index],
            )
        return MLCriterionResult(
            code=c.code,
            answer="no",
            evidence=[first_op.index],
            explanation="Operator answered without clarifying missing details.",
        )
