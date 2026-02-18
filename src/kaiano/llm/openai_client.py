from __future__ import annotations

import os
from typing import Any

from kaiano import logger as logger_mod

from ._json import parse_json, validate_json
from .base import LLMClient, LLMConfig
from .errors import LLMError
from .types import LLMMessage, LLMResult

log = logger_mod.get_logger()


class OpenAILLM(LLMClient):
    """OpenAI client wrapper.

    Supports two modes:
    - Structured Outputs (preferred) via Responses API json_schema
    - Fallback to JSON-only text output (still validated)
    """

    def __init__(self, config: LLMConfig):
        self._cfg = config
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise LLMError(f"Missing env var {config.api_key_env} for OpenAI API key")

        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise LLMError(
                "openai SDK not installed. Add dependency 'openai' or install kaiano with the llm extra."
            ) from e

        self._client = OpenAI(api_key=api_key)

    def _extract_output_text(self, resp: Any) -> str:
        # Newer SDKs expose output_text
        text = getattr(resp, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        # Fallback: try common shapes
        try:
            # responses: resp.output is a list of items with .content[]
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", None) in ("output_text", "text"):
                        t = getattr(c, "text", None)
                        if isinstance(t, str) and t.strip():
                            return t.strip()
        except Exception:
            pass

        raise LLMError("Unable to extract text from OpenAI response")

    def generate_json(
        self,
        *,
        messages: list[LLMMessage],
        json_schema: dict[str, Any],
        schema_name: str = "output",
    ) -> LLMResult:
        # Prefer Responses API Structured Outputs
        try:
            resp = self._client.responses.create(
                model=self._cfg.model,
                input=[{"role": m.role, "content": m.content} for m in messages],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": json_schema,
                        "strict": True,
                    }
                },
                timeout=self._cfg.timeout_s,
            )
            raw = self._extract_output_text(resp)
            data = parse_json(raw)
            validate_json(data, json_schema)
            return LLMResult(
                provider="openai", model=self._cfg.model, output_json=data, raw_text=raw
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "OpenAI structured output failed; falling back to JSON-only. err=%s", e
            )

        # Fallback: JSON-only response
        resp2 = self._client.chat.completions.create(
            model=self._cfg.model,
            messages=[{"role": m.role, "content": m.content} for m in messages]
            + [
                {
                    "role": "system",
                    "content": "Return ONLY valid JSON matching the requested schema. No markdown, no prose.",
                }
            ],
            temperature=0.2,
            timeout=self._cfg.timeout_s,
        )
        raw2 = (resp2.choices[0].message.content or "").strip()
        data2 = parse_json(raw2)
        validate_json(data2, json_schema)
        return LLMResult(
            provider="openai", model=self._cfg.model, output_json=data2, raw_text=raw2
        )
