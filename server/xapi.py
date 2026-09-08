"""X (Twitter) API adapter for market sentiment pullbacks."""
from __future__ import annotations

from typing import Any

import requests

from server.config import settings


def _x_headers() -> dict[str, str]:
    if not settings.X_API_BEARER_TOKEN:
        raise RuntimeError(
            "Set OA_X_API_BEARER_TOKEN before calling the X sentiment API. "
            "If you are using a free or app-only token, keep the X API base URL configured."
        )
    return {
        "Authorization": f"Bearer {settings.X_API_BEARER_TOKEN}",
        "User-Agent": "OSA-Market-Lab/0.1",
        "Content-Type": "application/json",
    }


def _build_query(symbol: str, max_results: int) -> str:
    query = f"{symbol} (stocks OR market OR trading) -is:retweet"
    return query[:280]


def fetch_symbol_sentiment(symbol: str, max_results: int = 10) -> dict[str, Any]:
    """Fetch recent public posts for a symbol and summarize them as a light sentiment signal."""
    cleaned = (symbol or "").strip().upper()
    if not cleaned:
        raise ValueError("A symbol is required to fetch X sentiment.")
    if max_results <= 0:
        raise ValueError("max_results must be positive.")

    query = _build_query(cleaned, max_results)
    url = f"{settings.X_API_BASE_URL.rstrip('/')}/2/tweets/search/recent"
    params = {
        "query": query,
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,public_metrics,lang",
        "expansions": "author_id",
        "user.fields": "username,name",
    }

    resp = requests.get(url, headers=_x_headers(), params=params, timeout=20)
    if resp.status_code == 401:
        raise RuntimeError("X API authentication failed. Check OA_X_API_BEARER_TOKEN.")
    if resp.status_code == 403:
        raise RuntimeError("X API access is blocked for this token or endpoint.")
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = {"error": resp.text}
        raise RuntimeError(f"X API request failed: {body}")

    body = resp.json()
    posts = body.get("data", [])
    sentiment_score = 0.0
    positive = 0
    negative = 0
    mentions = []

    for post in posts:
        text = post.get("text", "")
        engagement = post.get("public_metrics", {})
        retweets = engagement.get("retweet_count", 0)
        likes = engagement.get("like_count", 0)
        replies = engagement.get("reply_count", 0)
        score = (likes * 1.0) + (retweets * 2.0) + (replies * 1.5)

        lowercase = text.lower()
        if any(word in lowercase for word in ["bull", "buy", "breakout", "up", "strong", "momentum"]):
            sentiment_score += score
            positive += 1
        elif any(word in lowercase for word in ["bear", "sell", "breakdown", "down", "weak", "panic"]):
            sentiment_score -= score
            negative += 1

        mentions.append({
            "id": post.get("id"),
            "created_at": post.get("created_at"),
            "text": text,
            "engagement": engagement,
            "language": post.get("lang"),
        })

    total = max(len(posts), 1)
    normalized = (positive - negative) / total
    return {
        "symbol": cleaned,
        "query": query,
        "posts_found": len(posts),
        "positive_mentions": positive,
        "negative_mentions": negative,
        "sentiment_score": round(sentiment_score, 2),
        "normalized_sentiment": round(normalized, 4),
        "posts": mentions,
        "source": "x_api",
    }
