from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.news_agent import ClassifiedNews, _build_fallback_digest
from app.news_fetcher import NewsItem


class FallbackDigestTests(unittest.TestCase):
    def test_build_fallback_digest_contains_sections_and_links(self) -> None:
        items = [
            ClassifiedNews(
                item=NewsItem(
                    title="OpenAI 发布新模型",
                    link="https://example.com/a",
                    source="example",
                    published_at=datetime.now(UTC),
                    summary="模型能力更新",
                ),
                matched_keywords=["AI"],
                reason="核心主题相关",
            ),
            ClassifiedNews(
                item=NewsItem(
                    title="黄金价格波动",
                    link="https://example.com/b",
                    source="example",
                    published_at=datetime.now(UTC),
                    summary="市场避险情绪上升",
                ),
                matched_keywords=["黄金"],
                reason="金融市场相关",
            ),
        ]

        text = _build_fallback_digest(items, "AI、黄金")

        self.assertIn("【今日要点】", text)
        self.assertIn("【新闻速览】", text)
        self.assertIn("【团队建议】", text)
        self.assertIn("https://example.com/a", text)
        self.assertIn("https://example.com/b", text)


if __name__ == "__main__":
    unittest.main()
