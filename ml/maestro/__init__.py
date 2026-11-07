"""AI scoring of customer support chats against a quality checklist.

Public API for the backend:

    from maestro import OllamaClient, parse_bytes, score_transcript

    llm = OllamaClient.from_env()
    for transcript in parse_bytes("chat.json", raw_bytes):
        result = score_transcript(transcript, llm, output_language="ru")
        payload = result.model_dump(mode="json")
"""

from .ingest import IngestError, parse_bytes, parse_file, parse_json_object, parse_text
from .llm import LLMOutputError, LLMUnavailable, OllamaClient
from .pipeline import score_transcript
from .schemas import ScoreResult, Transcript

__all__ = [
    "IngestError",
    "LLMOutputError",
    "LLMUnavailable",
    "OllamaClient",
    "ScoreResult",
    "Transcript",
    "parse_bytes",
    "parse_file",
    "parse_json_object",
    "parse_text",
    "score_transcript",
]
