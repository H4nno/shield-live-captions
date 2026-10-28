"""Per-line translation via an OpenAI-compatible llama-server (llama.cpp).

If no URL is configured, or the server is down/slow, translation degrades to
pass-through: the German original is shown as the final line.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx

log = logging.getLogger("shieldcc.translate")

SYSTEM_TEMPLATE = (
    "You translate {src} TV and movie dialogue into {tgt}. "
    "Output ONLY the {tgt} translation. "
    "No quotes, no explanations, no notes. Keep it concise and natural, "
    "suitable as a subtitle. Preserve names and numbers."
)


class Translator:
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "local",
        timeout_s: float = 3.0,
        max_concurrent: int = 4,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.model = model
        self.timeout_s = timeout_s
        self.source_name = "German"
        self.target_name = "English"
        self._last_context = ""
        self._sem = asyncio.Semaphore(max_concurrent)
        self._client: Optional[httpx.AsyncClient] = None
        self.stats = {"translated": 0, "fallback": 0}

    def set_context(self, previous_line: str) -> None:
        """Remember the previous translated line for pronoun/tense context."""
        self._last_context = (previous_line or "")[:300]

    def set_languages(self, source_name: str, target_name: str) -> None:
        self.source_name = source_name
        self.target_name = target_name

    @property
    def passthrough(self) -> bool:
        return self.source_name == self.target_name

    def system_prompt(self) -> str:
        prompt = SYSTEM_TEMPLATE.format(src=self.source_name, tgt=self.target_name)
        if self._last_context:
            prompt += (
                "\nPrevious subtitle line, for context only — do NOT translate it, "
                "do NOT repeat it:\n" + self._last_context
            )
        return prompt

    async def start(self):
        if self.base_url:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
            log.info("translator enabled: %s (model=%s)", self.base_url, self.model)
        else:
            log.info("translator DISABLED (no TRANSLATE_URL) — passing German through")

    async def stop(self):
        if self._client:
            await self._client.aclose()

    async def translate(self, text: str) -> tuple[str, bool]:
        """Returns (target_language_text, was_translated)."""
        if not self._client or not text.strip() or self.passthrough:
            return text, False
        async with self._sem:
            try:
                r = await self._client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self.system_prompt()},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 160,
                    },
                )
                r.raise_for_status()
                out = r.json()["choices"][0]["message"]["content"].strip()
                # strip wrapping quotes models love to add
                out = re.sub(r'^["\u201c\u201e]+|["\u201d\u201c]+$', "", out).strip()
                if not out:
                    out = text
                    self.stats["fallback"] += 1
                    return out, False
                self.stats["translated"] += 1
                return out, True
            except Exception as e:
                log.warning("translation failed (%s) — falling back to original", e)
                self.stats["fallback"] += 1
                return text, False
