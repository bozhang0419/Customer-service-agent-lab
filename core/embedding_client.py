import os
import httpx
from typing import List

API_KEY = os.getenv("ANTHROPIC_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"


class EmbeddingClient:
    def __init__(self):
        self.key = API_KEY
        self.base = BASE_URL
        self.client = httpx.AsyncClient(timeout=40.0)

    async def get_text_embedding(self, text: str) -> List[float]:
        resp = await self.client.post(
            f"{self.base}/embeddings",
            headers={"Authorization": f"Bearer {self.key}"},
            json={
                "model": "deepseek-embedding",
                "input": text
            }
        )
        resp.raise_for_status()  # 捕获4xx/5xx网络错误
        data = resp.json()
        return data["data"][0]["embedding"]

    async def batch_embedding(self, text_list: List[str]) -> List[List[float]]:
        resp = await self.client.post(
            f"{self.base}/embeddings",
            headers={"Authorization": f"Bearer {self.key}"},
            json={
                "model": "deepseek-embedding",
                "input": text_list
            })
        resp.raise_for_status() # 捕获404、鉴权失败等异常
        data = resp.json()
        emb_list = [item["embedding"] for item in data["embedding"]]
        return emb_list
