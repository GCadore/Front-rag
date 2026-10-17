"""Texto: tokenizer/stemmer do BM25 e limpeza do corpo de issues (/triage, passo 1)."""
from __future__ import annotations

import importlib.util
import logging
import re
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("rag.text")

TEAM_BM25_SCRIPT = "05b_bm25_index.py"


# --------------------------------------------------------------------------- #
# Tokenizer do BM25
#
# A query PRECISA passar pelo mesmo pré-processamento do índice salvo:
# bm25s.tokenize com o stemmer get_stemmer("english") e as stopwords de
# config.yaml (bm25.stopwords). Se o 05b_bm25_index.py do time estiver no
# path, usamos o get_stemmer de lá; senão, o equivalente com PyStemmer.
# --------------------------------------------------------------------------- #
DEFAULT_STEMMER_LANG = "english"
DEFAULT_STOPWORDS = "en"


def _load_team_get_stemmer(search_paths: Iterable[Path]) -> Any | None:
    for base in search_paths:
        path = Path(base) / TEAM_BM25_SCRIPT
        if not path.is_file():
            continue
        try:
            # O nome começa com dígito, então precisa de spec_from_file_location.
            # Obs.: se o script não tiver `if __name__ == "__main__":`, importar
            # executa o código do topo. Confira antes de deixar o arquivo no path.
            spec = importlib.util.spec_from_file_location("team_bm25_index", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = getattr(module, "get_stemmer", None)
            if callable(fn):
                log.info("Usando get_stemmer de %s", path)
                return fn
        except Exception:  # noqa: BLE001 - qualquer falha cai no fallback
            log.exception("Falha ao importar %s; usando fallback", path)
    return None


def get_stemmer(lang: str = DEFAULT_STEMMER_LANG) -> Any:
    """Equivalente ao get_stemmer do 05b_bm25_index.py: PyStemmer na língua pedida."""
    import Stemmer  # PyStemmer; import tardio

    return Stemmer.Stemmer(lang)


def load_stemmer(bm25_cfg: dict[str, Any], search_paths: Iterable[Path] = ()) -> Any | None:
    lang = str(bm25_cfg.get("stemmer", DEFAULT_STEMMER_LANG))
    if lang.lower() in {"none", "false", "off", ""}:
        return None
    team_fn = _load_team_get_stemmer(search_paths)
    return (team_fn or get_stemmer)(lang)


def stopwords_from_config(bm25_cfg: dict[str, Any]) -> Any:
    """bm25.stopwords do config.yaml: uma língua ("en"), uma lista de palavras ou nada."""
    value = bm25_cfg.get("stopwords", DEFAULT_STOPWORDS)
    if value is None or value is False:
        return None
    if isinstance(value, (list, tuple, set)):
        return [str(w).lower() for w in value]
    return str(value)


class BM25Tokenizer:
    """Tokeniza corpus e queries com as mesmas stopwords e stemmer do índice."""

    def __init__(self, bm25_cfg: dict[str, Any], search_paths: Iterable[Path] = ()):
        self.stopwords = stopwords_from_config(bm25_cfg)
        self.lower = bool(bm25_cfg.get("lower", True))
        self.stemmer = load_stemmer(bm25_cfg, search_paths)

    def _kwargs(self) -> dict[str, Any]:
        return {"lower": self.lower, "stopwords": self.stopwords, "stemmer": self.stemmer, "show_progress": False}

    def corpus(self, texts: list[str]) -> Any:
        """Retorna o `Tokenized` (ids + vocab) para BM25.index()."""
        import bm25s

        return bm25s.tokenize(texts, **self._kwargs())

    def query(self, text: str) -> list[str]:
        """Tokens (strings, já com stem) da query; o bm25s mapeia para o vocabulário do índice."""
        import bm25s

        tokens = bm25s.tokenize([text], return_ids=False, **self._kwargs())
        return list(tokens[0]) if tokens else []


# --------------------------------------------------------------------------- #
# Limpeza do corpo da issue (spec /triage, passo 1)
# --------------------------------------------------------------------------- #
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
EMPTY_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[\s\]\s*.*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
MAX_CODE_LINES = 15


def _truncate_code_blocks(lines: list[str], max_lines: int = MAX_CODE_LINES) -> list[str]:
    """Mantém só as primeiras `max_lines` linhas de cada bloco de código."""
    out: list[str] = []
    inside = False
    kept = 0
    cut = False
    for line in lines:
        if FENCE_RE.match(line):
            if inside and cut:
                out.append("[... log cortado ...]")
            inside, kept, cut = not inside, 0, False
            out.append(line)
            continue
        if inside:
            if kept < max_lines:
                out.append(line)
                kept += 1
            else:
                cut = True
            continue
        out.append(line)
    if inside and cut:  # bloco sem fechamento
        out.append("[... log cortado ...]")
    return out


def _drop_empty_sections(lines: list[str]) -> list[str]:
    """Remove títulos de template cuja seção ficou vazia."""
    out: list[str] = []
    for i, line in enumerate(lines):
        if HEADING_RE.match(line):
            rest = lines[i + 1 :]
            nxt = next((r for r in rest if r.strip()), None)
            if nxt is None or HEADING_RE.match(nxt):
                continue
        out.append(line)
    return out


def clean_issue_body(body: str) -> str:
    text = HTML_COMMENT_RE.sub("", body or "")
    lines = [ln for ln in text.splitlines() if not EMPTY_CHECKBOX_RE.match(ln)]
    lines = _truncate_code_blocks(lines)
    lines = _drop_empty_sections(lines)
    cleaned = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def approx_tokens(text: str) -> int:
    """Aproximação simples: ~4 caracteres por token."""
    return (len(text) + 3) // 4
