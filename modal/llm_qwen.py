"""LLM do projeto no Modal: Qwen3.5-9B servido pelo vLLM com API no formato da OpenAI.

    python scripts/deploy_modal.py            (deploy do LLM + API e grava a URL no .env.local)
    modal deploy modal/llm_qwen.py            (só este app)
    modal run modal/llm_qwen.py::download_model   (pré-baixa os pesos no Volume; o setup já faz)

URL: https://<seu-workspace>--<RAG_LLM_APP>-serve.modal.run/v1
Autenticação: "Authorization: Bearer <LLM_API_KEY>" (secret RAG_MODAL_SECRET, criado pelo setup).

Tudo configurável por variável de ambiente NA HORA DO DEPLOY (os valores vão para a imagem):
    RAG_LLM_APP         nome do app                     (padrão backstage-rag-llm)
    RAG_MODAL_SECRET    secret com LLM_API_KEY          (padrão backstage-rag-keys)
    LLM_MODEL_ID        modelo do Hugging Face          (padrão Qwen/Qwen3.5-9B)
    LLM_GPU             GPU do Modal                    (padrão A10G; L4, L40S, A100...)
    LLM_QUANTIZATION    fp8 | none                      (padrão fp8)
    LLM_MAX_MODEL_LEN   contexto máximo                 (padrão 32768)
    HF_CACHE_VOLUME     Volume com os pesos             (padrão huggingface-cache)

Memória: o Qwen3.5-9B em bf16 não cabe numa GPU de 24 GB (A10G/L4) junto com o cache de KV e os
CUDA graphs (testado: OOM). Com LLM_QUANTIZATION=fp8 (pesos em 8 bits, quantizados ao carregar)
ocupa ~10 GB e sobra memória para 32k de contexto. Em GPU de 48 GB+ (L40S, A100) dá para usar
LLM_QUANTIZATION=none.

Thinking: o Qwen3.5 pensa por padrão; o backend desliga por requisição com
extra_body={"chat_template_kwargs": {"enable_thinking": false}} (LLM_ENABLE_THINKING no backend).
"""
from __future__ import annotations

import os
import subprocess

import modal

APP_NAME = os.environ.get("RAG_LLM_APP", "backstage-rag-llm")
SECRET_NAME = os.environ.get("RAG_MODAL_SECRET", "backstage-rag-keys")
MODEL = os.environ.get("LLM_MODEL_ID", "Qwen/Qwen3.5-9B")
GPU = os.environ.get("LLM_GPU", "A10G")
QUANTIZATION = os.environ.get("LLM_QUANTIZATION", "fp8")
MAX_MODEL_LEN = os.environ.get("LLM_MAX_MODEL_LEN", "32768")
HF_CACHE_VOLUME = os.environ.get("HF_CACHE_VOLUME", "huggingface-cache")
VLLM_VERSION = "0.31.0"   # precisa de vLLM com suporte a Qwen3.5 (Qwen3_5ForConditionalGeneration)
PORT = 8000
HF_DIR = "/root/.cache/huggingface"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(f"vllm=={VLLM_VERSION}", "huggingface_hub")
    .env({
        # gravados na imagem para o container ver os mesmos valores do deploy
        "LLM_MODEL_ID": MODEL, "LLM_QUANTIZATION": QUANTIZATION, "LLM_MAX_MODEL_LEN": MAX_MODEL_LEN,
        "HF_XET_HIGH_PERFORMANCE": "1",
        # A imagem slim não tem nvcc; o sampler do FlashInfer tenta compilar (JIT) e quebra.
        # O sampler nativo do vLLM é equivalente para o nosso uso.
        "VLLM_USE_FLASHINFER_SAMPLER": "0",
    })
)

hf_cache = modal.Volume.from_name(HF_CACHE_VOLUME, create_if_missing=True)
vllm_cache = modal.Volume.from_name("vllm-cache", create_if_missing=True)

app = modal.App(APP_NAME)


@app.function(image=image, volumes={HF_DIR: hf_cache}, timeout=60 * 60, cpu=4)
def download_model() -> str:
    """Baixa os pesos para o Volume (sem GPU). O 1º cold start fica bem mais rápido."""
    from huggingface_hub import snapshot_download

    path = snapshot_download(MODEL, ignore_patterns=["*.pt", "*.bin", "original/*"])
    hf_cache.commit()
    print("Pesos em", path)
    return path


@app.function(
    image=image,
    gpu=GPU,
    volumes={HF_DIR: hf_cache, "/root/.cache/vllm": vllm_cache},
    secrets=[modal.Secret.from_name(SECRET_NAME, required_keys=["LLM_API_KEY"])],
    timeout=60 * 60,
    min_containers=0,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=16)
@modal.web_server(port=PORT, startup_timeout=20 * 60)
def serve() -> None:
    key = os.environ["LLM_API_KEY"]
    cmd = [
        "vllm", "serve", MODEL,
        "--served-model-name", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--max-model-len", MAX_MODEL_LEN,
        "--max-num-seqs", "16",
        "--gpu-memory-utilization", "0.90",
        "--language-model-only",          # só texto: não carrega o encoder de visão
        "--reasoning-parser", "qwen3",    # se o thinking for ligado, ele sai em reasoning_content
        "--api-key", key,
        "--uvicorn-log-level", "warning",
    ]
    if QUANTIZATION and QUANTIZATION.lower() != "none":
        cmd += ["--quantization", QUANTIZATION]
    print("Iniciando:", " ".join("***" if c == key else c for c in cmd), flush=True)
    subprocess.Popen(cmd)
