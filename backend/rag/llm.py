"""Cliente do LLM via SDK `openai` (vLLM no Modal, Ollama local, RunPod: só muda o .env).

Qwen3.5 pensa (thinking) por padrão. Desligamos por requisição com
    extra_body={"chat_template_kwargs": {"enable_thinking": False}}
que o vLLM repassa ao chat template (LLM_ENABLE_THINKING=true liga de novo). No Ollama o mesmo
efeito vem de "reasoning_effort": "none"; mandamos os dois, e cada servidor ignora o que não conhece.
Se mesmo assim vier um bloco <think>...</think> no texto, ele é removido.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, AsyncIterator, Protocol

FRIENDLY_LLM_ERROR = "O modelo de linguagem não respondeu agora. Tente de novo em alguns instantes."
THINK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


class LLMError(Exception):
    """Qualquer falha do LLM (timeout, conexão, resposta inválida) -> HTTP 502."""


class LLM(Protocol):
    model: str

    async def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0.1, json_mode: bool = False
    ) -> str: ...

    def stream(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> AsyncIterator[str]: ...


def strip_think(text: str) -> str:
    text = THINK_RE.sub("", text)
    if text.lstrip().startswith("</think>"):  # template que já abre o <think> no prompt
        text = text.split("</think>", 1)[1].lstrip()
    return text


def thinking_extra_body(enable_thinking: bool, base_url: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
    if not enable_thinking and ":11434" in base_url:  # Ollama
        body["reasoning_effort"] = "none"
    return body


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float | None = None,
        enable_thinking: bool | None = None,
        max_tokens: int | None = None,
    ):
        """Parâmetros não informados vêm do ambiente: LLM_TIMEOUT_S (120), LLM_ENABLE_THINKING (false),
        LLM_MAX_TOKENS (2048). Assim o api.py continua chamando OpenAICompatLLM(base_url, key, model, timeout)."""
        from openai import AsyncOpenAI  # import tardio

        if timeout_s is None:
            timeout_s = float(os.getenv("LLM_TIMEOUT_S", "120"))
        if enable_thinking is None:
            enable_thinking = os.getenv("LLM_ENABLE_THINKING", "false").strip().lower() in {"1", "true", "yes", "on", "sim"}
        if max_tokens is None:
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2048"))

        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.extra_body = thinking_extra_body(enable_thinking, base_url)
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key or "none", timeout=timeout_s, max_retries=1)

    async def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0.1, json_mode: bool = False
    ) -> str:
        kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            resp = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=temperature,  # type: ignore[arg-type]
                    max_tokens=self.max_tokens, extra_body=self.extra_body, **kwargs,
                ),
                timeout=self.timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        if not resp.choices:
            raise LLMError("Resposta sem choices")
        return strip_think(resp.choices[0].message.content or "")

    async def stream(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> AsyncIterator[str]:
        deadline = time.monotonic() + self.timeout_s  # tempo total, não por chunk
        buffer, inside_think, started = "", False, False
        try:
            stream = await self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=temperature, stream=True,  # type: ignore[arg-type]
                max_tokens=self.max_tokens, extra_body=self.extra_body,
            )
            async for chunk in stream:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"LLM passou de {self.timeout_s:.0f} s")
                if not (chunk.choices and chunk.choices[0].delta.content):
                    continue
                piece = chunk.choices[0].delta.content
                if started:
                    yield piece
                    continue
                # Antes do 1º texto: descarta um eventual bloco <think>...</think>
                buffer += piece
                if inside_think or buffer.lstrip().startswith("<think>"):
                    inside_think = True
                    if "</think>" not in buffer:
                        continue
                    buffer = buffer.split("</think>", 1)[1].lstrip()
                    inside_think = False
                if not buffer or "<think>".startswith(buffer.lstrip()):
                    continue  # ainda pode ser o começo de "<think>"
                started = True
                yield buffer
            if not started and buffer and not inside_think:
                yield buffer
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
