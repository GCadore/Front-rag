"""Cliente do LLM via SDK `openai` (Ollama, vLLM no Modal/RunPod: só muda o .env)."""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, Protocol

FRIENDLY_LLM_ERROR = "O modelo de linguagem não respondeu agora. Tente de novo em alguns instantes."


class LLMError(Exception):
    """Qualquer falha do LLM (timeout, conexão, resposta inválida) -> HTTP 502."""


class LLM(Protocol):
    model: str

    async def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0.1, json_mode: bool = False
    ) -> str: ...

    def stream(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> AsyncIterator[str]: ...


class OpenAICompatLLM:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: float = 120.0):
        from openai import AsyncOpenAI  # import tardio

        self.model = model
        self.timeout_s = timeout_s
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key or "none", timeout=timeout_s, max_retries=1)

    async def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0.1, json_mode: bool = False
    ) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            resp = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=temperature, **kwargs  # type: ignore[arg-type]
                ),
                timeout=self.timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        if not resp.choices:
            raise LLMError("Resposta sem choices")
        return resp.choices[0].message.content or ""

    async def stream(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> AsyncIterator[str]:
        deadline = time.monotonic() + self.timeout_s  # 120 s no total, não por chunk
        try:
            stream = await self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=temperature, stream=True  # type: ignore[arg-type]
            )
            async for chunk in stream:
                if time.monotonic() > deadline:
                    raise TimeoutError("LLM passou de 120 s")
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
