"""统一向量入口：默认真实语义向量，可切回历史哈希实现做对照。

历史实现（intent_recognizer / knowledge_base / conversation_memory 各自复制了一份
`_local_embedding`）是 256 维字符 n-gram 哈希向量：稀疏、未归一化，L2 距离主要由
文本长度而非语义决定，因此对外宣称的"语义检索"实际是模糊关键词匹配。

现在默认走 Chroma 内置的 all-MiniLM-L6-v2（ONNX，384 维，纯本地推理，无外部调用、
无额外依赖、离线可用）。设 EMBEDDING_BACKEND=hash 可切回旧实现，用于复现改前基线。
"""
import hashlib
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

HASH_DIMS = 256
ONNX_DIMS = 384

_onnx_fn = None


def backend() -> str:
    return (os.getenv("EMBEDDING_BACKEND") or "onnx").strip().lower()


def embedding_dims() -> int:
    return HASH_DIMS if backend() == "hash" else ONNX_DIMS


def _get_onnx_fn():
    global _onnx_fn
    if _onnx_fn is None:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        _onnx_fn = ONNXMiniLM_L6_V2()
    return _onnx_fn


def hash_embedding(text: str, dims: int = HASH_DIMS) -> List[float]:
    """历史实现的字符 n-gram 哈希向量，仅在 EMBEDDING_BACKEND=hash 时使用。"""
    normalized = text.lower().strip()
    vec = [0.0] * dims
    tokens = set()
    for n in (1, 2, 3):
        if len(normalized) >= n:
            tokens.update(normalized[i:i + n] for i in range(len(normalized) - n + 1))
    if not tokens:
        tokens.add(normalized)
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dims
        vec[idx] += 1.0 if digest[4] % 2 == 0 else -1.0
    return vec


def embed_texts(texts: List[str]) -> List[List[float]]:
    if backend() == "hash":
        return [hash_embedding(t) for t in texts]
    return [[float(x) for x in v] for v in _get_onnx_fn()(texts)]


def embed_text(text: str) -> List[float]:
    return embed_texts([text])[0]


def ensure_collection(client, name: str, description: str):
    """按当前后端取集合；后端或维度变了就重建——旧向量不可复用，硬用会报维度错。"""
    want: Dict[str, Any] = {
        "description": description,
        "embedding_backend": backend(),
        "embedding_dims": str(embedding_dims()),
    }
    collection = client.get_or_create_collection(name=name, metadata=want)
    got = collection.metadata or {}
    if got.get("embedding_backend") != want["embedding_backend"] or got.get("embedding_dims") != want["embedding_dims"]:
        dropped = collection.count()
        logger.warning(
            "集合 %s 向量后端变更（%s→%s / %s→%s 维），重建并丢弃 %d 个旧片段",
            name, got.get("embedding_backend"), want["embedding_backend"],
            got.get("embedding_dims"), want["embedding_dims"], dropped,
        )
        client.delete_collection(name)
        collection = client.get_or_create_collection(name=name, metadata=want)
    return collection
