"""
RAG 知识库 —— 基于 ChromaDB 的真实检索实现。
弃用Chroma内置all-MiniLM，统一调用DeepSeek线上向量接口
"""
import hashlib
import logging
from typing import Any, Dict, List, Optional

import chromadb
from core.embedding_client import EmbeddingClient
logger = logging.getLogger(__name__)

def _local_embedding(text: str, dims: int = 256) -> list[float]:
    """
    本地字符n-gram哈希向量生成
    与原项目意图识别模块的Embedding兜底逻辑完全一致
    不调用任何外部接口，纯本地计算
    """
    normalized = text.lower().strip()
    vec = [0.0] * dims
    tokens = set()
    # 1/2/3元字符哈希，固定输出256维向量
    for n in (1, 2, 3):
        if len(normalized) >= n:
            tokens.update(normalized[i:i+n] for i in range(len(normalized) - n + 1))
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    return vec

class KnowledgeBase:
    COLLECTION_NAME = "knowledge_base"

    def __init__(
        self,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        chroma_path: str = "./data/chroma",
    ):
        self._use_server = False
        self._client = chromadb.PersistentClient(
            path=chroma_path,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        logger.info(f"知识库【本地文件模式】启动，数据存放路径: {chroma_path}")

        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "EchoMind RAG 知识库"},
        )
        self.emb_client = EmbeddingClient()

    async def add_documents(self, documents: List[Dict[str, str]]) -> int:
        ids, docs, metas = [], [], []

        for doc in documents:
            title   = doc.get("title", "")
            content = doc.get("content", "")
            chunks  = self._chunk_text(content, chunk_size=500)

            for i, chunk in enumerate(chunks):
                doc_id = hashlib.md5(f"{title}_{i}_{chunk[:50]}".encode()).hexdigest()
                ids.append(doc_id)
                docs.append(chunk)
                metas.append({"title": title, "chunk_index": i, "total_chunks": len(chunks)})

        if ids:
            embeddings = [_local_embedding(doc) for doc in docs]
            self._collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=docs,
                metadatas=metas
            )
            logger.info(f"知识库导入 {len(ids)} 个文档片段")

        return len(ids)

    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        emb = _local_embedding(query)
        results = self._collection.query(
            query_embeddings=[emb],
            n_results=top_k,
        )

        items = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                items.append({
                    "title":    meta.get("title", ""),
                    "content":  doc,
                    # Chroma 默认 L2 距离 ∈ [0, +∞)，直接 1.0 - dist 不构成相似度且可能为负；
                    # 用 1/(1+d) 单调映射到 (0, 1]，距离越小分数越高，便于展示与阈值判断。
                    "score":    round(1.0 / (1.0 + dist), 4),
                    "chunk":    meta.get("chunk_index", 0),
                })

        return items

    @property
    def doc_count(self) -> int:
        return self._collection.count()

    async def search_handler(self, params: Dict[str, Any], context: Any) -> List[Dict]:
        query = params.get("query", "")
        top_k = params.get("top_k", 5)
        return await self.search(query, top_k=top_k)

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        current = ""
        sentences = text.replace("\n", "。").split("。")
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 > chunk_size:
                if current:
                    chunks.append(current)
                current = sent
            else:
                current = f"{current}。{sent}" if current else sent

        if current:
            chunks.append(current)

        return chunks

    async def _load_default_docs(self) -> None:
        default_docs = [
            {
                "title": "退款政策",
                "content": (
                    "退款政策说明。"
                    "用户在购买后 7 天内可以申请无理由退款。"
                    "退款申请提交后，系统会在 1-3 个工作日内审核。"
                    "审核通过后，款项将在 5-7 个工作日内退回原支付账户。"
                    "如果商品已发货，需要先完成退货流程才能退款。"
                    "退货运费由用户承担，除非是商品质量问题。"
                    "超过 7 天但未超过 30 天的订单，需要提供商品质量问题的证据才能退款。"
                ),
            },
            {
                "title": "订单查询",
                "content": (
                    "订单查询指南。"
                    "用户可以通过订单号查询订单状态。"
                    "订单状态包括：待支付、已支付、已发货、运输中、已签收、已完成。"
                    "如果订单显示已发货但超过 7 天未收到，可以联系客服申请查件。"
                    "物流信息通常在发货后 24 小时内更新。"
                    "如果订单显示异常，请提供订单号联系客服处理。"
                ),
            },
            {
                "title": "账户安全",
                "content": (
                    "账户安全说明。"
                    "建议用户定期修改密码，密码长度至少 8 位，包含字母和数字。"
                    "如果忘记密码，可以通过绑定的手机号或邮箱重置。"
                    "发现账户异常登录时，系统会自动锁定账户并发送通知。"
                    "用户可以在安全设置中开启两步验证，提高账户安全性。"
                    "不要将密码分享给他人，客服人员不会索要用户密码。"
                ),
            },
            {
                "title": "技术故障排查",
                "content": (
                    "常见技术问题排查。"
                    "应用崩溃：请尝试清除缓存后重启应用，如果问题持续请更新到最新版本。"
                    "登录失败 401 错误：表示认证失败，请检查用户名密码是否正确，或尝试重置密码。"
                    "页面加载慢：检查网络连接，尝试切换 WiFi 或移动数据。"
                    "支付失败：确认银行卡余额充足，检查是否开启了网上支付功能。"
                    "500 服务器错误：这是服务端问题，请稍后重试，如果持续出现请联系技术支持。"
                ),
            },
            {
                "title": "会员与积分",
                "content": (
                    "会员积分规则。"
                    "每消费 1 元累积 1 积分。"
                    "积分可以在下次购物时抵扣，100 积分 = 1 元。"
                    "会员等级分为：普通会员、银卡会员（累计消费 1000 元）、金卡会员（累计消费 5000 元）。"
                    "银卡会员享受 95 折优惠，金卡会员享受 9 折优惠。"
                    "积分有效期为 1 年，过期自动清零。"
                    "生日当月消费可获得双倍积分。"
                ),
            },
            {
                "title": "配送说明",
                "content": (
                    "配送服务说明。"
                    "标准配送：3-5 个工作日送达，免运费（订单满 99 元）。"
                    "加急配送：1-2 个工作日送达，运费 15 元。"
                    "同城配送：当日达或次日达，运费 10 元。"
                    "偏远地区可能需要额外 2-3 天。"
                    "配送时间为每天 9:00-18:00，节假日可能延迟。"
                    "如果需要修改收货地址，请在发货前联系客服。"
                ),
            },
        ]
        await self.add_documents(default_docs)
        logger.info(f"已导入默认知识库: {len(default_docs)} 篇文档")
