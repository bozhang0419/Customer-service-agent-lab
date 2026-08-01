"""
三级记忆模块：Redis短时会话 + Chroma情景摘要 + 用户画像
使用DeepSeek外部向量，不下载境外模型
"""
import json
import logging
import hashlib
from enum import Enum
from typing import List, Dict, Optional
import redis.asyncio as redis
import chromadb
from core.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)
def _local_embedding(text: str, dims: int = 256) -> list[float]:
    """本地n-gram哈希向量，不调用任何远程Embedding接口，与知识库逻辑统一"""
    normalized = text.lower().strip()
    vec = [0.0] * dims
    tokens = set()
    # 1/2/3字符分词哈希
    for n in (1, 2, 3):
        if len(normalized) >= n:
            tokens.update(normalized[i:i+n] for i in range(len(normalized) - n + 1))
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    return vec

class MsgRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MemoryManager:
    HISTORY_TOP_K = 3
    WORKING_MAX = 20
    COMPRESS_AT = 15
    REDIS_TTL_SEC = 86400

    def __init__(
        self,
        redis_url: str,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        chroma_path: str = "./data/chroma",
        api_key=None,
        base_url=None,
        model=None
    ):
        self.redis = redis.from_url(redis_url)
        self.emb_client = EmbeddingClient()

        self._chroma_client = None
        self._episodic = None
        self._profile = None
        self._init_chroma(chroma_host, chroma_port, chroma_path)

    def _init_chroma(self, host, port, path):
        try:
            self._chroma_client = chromadb.HttpClient(host=host, port=port, settings=chromadb.Settings(anonymized_telemetry=False))
            self._chroma_client.heartbeat()
        except Exception:
            self._chroma_client = chromadb.PersistentClient(path=path, settings=chromadb.Settings(anonymized_telemetry=False))

        self._episodic = self._chroma_client.get_or_create_collection(name="episodic", metadata={"desc":"会话摘要记忆"})
        self._profile = self._chroma_client.get_or_create_collection(name="user_profile", metadata={"desc":"用户画像"})

    def _safe_text(self, s: str) -> str:
        if not s:
            return ""
        return s.strip()

    async def get_working_memory(self, user_id: str, conv_id: str) -> List[Dict]:
        key = f"wm:{user_id}:{conv_id}"
        raw = await self.redis.lrange(key, 0, -1)
        res = []
        for item in raw:
            try:
                res.append(json.loads(item))
            except:
                pass
        return list(reversed(res))

    async def append_working_memory(self, user_id: str, conv_id: str, role: str, content: str):
        key = f"wm:{user_id}:{conv_id}"
        data = json.dumps({"role": role, "content": self._safe_text(content)})
        await self.redis.lpush(key, data)
        await self.redis.expire(key, self.REDIS_TTL_SEC)

        length = await self.redis.llen(key)
        if length >= self.COMPRESS_AT:
            await self._compress_history(user_id, conv_id)

    async def _compress_history(self, user_id: str, conv_id: str):
        wm_key = f"wm:{user_id}:{conv_id}"
        all_raw = await self.redis.lrange(wm_key, 0, -1)
        full_msgs = []
        for r in all_raw:
            try:
                full_msgs.append(json.loads(r))
            except:
                continue
        keep = full_msgs[:5]
        to_compress = full_msgs[5:]
        if not to_compress:
            return

        full_text = "\n".join([f"{m['role']}: {m['content']}" for m in to_compress])
        summary = f"历史对话摘要：{full_text[:800]}"
        await self._store_episodic(user_id, conv_id, summary, full_text)

        await self.redis.delete(wm_key)
        for msg in reversed(keep):
            await self.redis.lpush(wm_key, json.dumps(msg))
        logger.info(f"工作记忆压缩完成 user={user_id} conv={conv_id}")

    async def _store_episodic(self, user_id: str, conv_id: str, summary: str, full_text: str):
        text = self._safe_text(summary)
        if not text:
            return
        doc_id = hashlib.md5(f"{user_id}_{conv_id}_{text[:100]}".encode()).hexdigest()
        emb = _local_embedding(text)
        meta = {
            "user_id": user_id,
            "conv_id": conv_id,
            "full_text": full_text
        }
        self._episodic.add(
            ids=[doc_id],
            embeddings=[emb],
            documents=[text],
            metadatas=[meta]
        )

    async def _search_episodic(self, user_id: str, query: str) -> List[str]:
        query_text = self._safe_text(query).strip()
        if not query_text:
            return []
        try:
            emb = _local_embedding(query_text)
            results = self._episodic.query(
                query_embeddings=[emb],
                n_results=self.HISTORY_TOP_K,
                where={"user_id": user_id},
            )
            docs = results["documents"][0] if results["documents"] else []
            return [self._safe_text(d) for d in docs if d and d.strip()]
        except Exception as e:
            logger.warning(f"情景记忆检索失败: {e}")
            return []

    async def update_user_profile(self, user_id: str, profile_text: str):
        text = self._safe_text(profile_text)
        if not text:
            return
        doc_id = hashlib.md5(f"profile_{user_id}".encode()).hexdigest()
        emb = _local_embedding(text)
        meta = {"user_id": user_id}
        try:
            # upsert：doc_id 固定为 profile_{user_id}，覆盖写入即达到“更新画像”语义，
            # 避免原 delete(where={...}) 参数缺值被静默吞掉、以及 delete 失败后 add 撞主键。
            self._profile.upsert(
                ids=[doc_id],
                embeddings=[emb],
                documents=[text],
                metadatas=[meta]
            )
        except Exception as e:
            logger.warning(f"用户画像更新失败: {e}")
            return
        logger.info(f"用户画像更新完成 user={user_id}")

    async def get_user_profile(self, user_id: str) -> str:
        try:
            res = self._profile.get(where={"user_id": user_id})
            if res["documents"] and len(res["documents"]) > 0:
                return res["documents"][0]
            return ""
        except Exception as e:
            logger.warning(f"读取用户画像失败: {e}")
            return ""

    async def get_memory_context(self, user_id: str, conv_id: str, query: str):
        working = await self.get_working_memory(user_id, conv_id)
        history_summary = await self._search_episodic(user_id, query)
        profile = await self.get_user_profile(user_id)
        return {
            "working_memory": working,
            "history_summary": history_summary,
            "user_profile": profile
        }
