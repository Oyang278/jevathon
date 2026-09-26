import asyncio
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Jev:
    def __init__(self, concurrency: int = 32):
        load_dotenv(ENV_FILE)
        key = os.environ.get("TYPESAFE_API_KEY")
        if not key:
            raise RuntimeError(f"TYPESAFE_API_KEY is not set (looked in environment and {ENV_FILE})")
        default_url = (
            "https://jevtypesafeai.com/api/v1/decide"
            if key.startswith("jv_live_")
            else "https://api.typesafe.ai/v1/systemone"
        )
        self.url = os.environ.get("JEV_URL", default_url)
        self.model = os.environ.get("JEV_MODEL", "jev-latest")
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {key}"}, timeout=30
        )
        self.sem = asyncio.Semaphore(concurrency)
        self.calls = 0
        self.input_tokens = 0
        self.total_latency = 0.0

    @property
    def cost(self) -> float:
        return self.input_tokens * PRICE_PER_INPUT_TOKEN

    @property
    def avg_latency_ms(self) -> float:
        return 1000 * self.total_latency / self.calls if self.calls else 0.0

    async def ask(self, state, questions: dict) -> tuple[dict, float]:
        body = {"model": self.model, "state": state, "questions": questions}
        async with self.sem:
            for attempt in range(6):
                start = time.perf_counter()
                try:
                    res = await self.client.post(self.url, json=body)
                except httpx.TransportError:
                    if attempt == 5:
                        raise
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                if res.status_code == 429 or res.status_code >= 500:
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                if res.status_code >= 400:
                    raise RuntimeError(f"Jev error {res.status_code}: {res.text[:300]}")
                latency = time.perf_counter() - start
                data = res.json()
                self.calls += 1
                self.total_latency += latency
                self.input_tokens += data.get("usage", {}).get("input_tokens", 0)
                return data["answers"], latency
            raise RuntimeError(f"Jev kept failing: {res.status_code} {res.text[:200]}")

    async def close(self):
        await self.client.aclose()
