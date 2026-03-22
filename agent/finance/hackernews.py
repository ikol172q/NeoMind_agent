# agent/finance/hackernews.py
"""
Hacker News Integration — fetch top/best/new stories from HN API.

API: https://hacker-news.firebaseio.com/v0/ (free, no auth, no rate limit)

Features:
- Fetch top/best/new stories with title, URL, score, comments
- Filter by minimum score
- Deduplicate against previously pushed stories (SQLite)
- Format for Telegram (compact, readable)
"""

import time
import asyncio
import requests
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone


HN_API = "https://hacker-news.firebaseio.com/v0"


@dataclass
class HNStory:
    id: int
    title: str
    url: str = ""
    score: int = 0
    by: str = ""
    descendants: int = 0  # comment count
    time: int = 0
    type: str = "story"

    @property
    def hn_url(self) -> str:
        return f"https://news.ycombinator.com/item?id={self.id}"

    @property
    def display_url(self) -> str:
        return self.url or self.hn_url

    @property
    def age_hours(self) -> float:
        if not self.time:
            return 0
        return (time.time() - self.time) / 3600


def fetch_story(story_id: int) -> Optional[HNStory]:
    """Fetch a single story by ID."""
    try:
        resp = requests.get(f"{HN_API}/item/{story_id}.json", timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data or data.get("type") not in ("story", "job"):
            return None
        return HNStory(
            id=data.get("id", 0),
            title=data.get("title", ""),
            url=data.get("url", ""),
            score=data.get("score", 0),
            by=data.get("by", ""),
            descendants=data.get("descendants", 0),
            time=data.get("time", 0),
            type=data.get("type", "story"),
        )
    except Exception:
        return None


async def fetch_top_stories(
    category: str = "top",
    limit: int = 10,
    min_score: int = 0,
) -> List[HNStory]:
    """Fetch top/best/new stories from HN.

    Args:
        category: "top", "best", "new", "ask", "show", "job"
        limit: max stories to return
        min_score: minimum score filter (0 = no filter)
    """
    endpoint = {
        "top": "topstories",
        "best": "beststories",
        "new": "newstories",
        "ask": "askstories",
        "show": "showstories",
        "job": "jobstories",
    }.get(category, "topstories")

    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: requests.get(f"{HN_API}/{endpoint}.json", timeout=10)
        )
        if resp.status_code != 200:
            return []
        story_ids = resp.json()[:limit * 2]  # fetch extra for score filtering
    except Exception:
        return []

    # Fetch stories in parallel (batch of 10)
    stories = []
    for i in range(0, len(story_ids), 10):
        batch = story_ids[i:i+10]
        results = await asyncio.gather(
            *[loop.run_in_executor(None, fetch_story, sid) for sid in batch]
        )
        for s in results:
            if s and (min_score == 0 or s.score >= min_score):
                stories.append(s)
            if len(stories) >= limit:
                break
        if len(stories) >= limit:
            break

    return stories[:limit]


def format_stories_telegram(stories: List[HNStory], title: str = "Hacker News") -> str:
    """Format stories for Telegram message (HTML)."""
    if not stories:
        return "没有找到 HN 文章"

    lines = [f"🔶 <b>{title}</b>\n"]
    for i, s in enumerate(stories, 1):
        comments_url = s.hn_url
        age = f"{s.age_hours:.0f}h" if s.age_hours < 24 else f"{s.age_hours/24:.0f}d"

        lines.append(
            f"{i}. <a href=\"{s.display_url}\">{s.title}</a>\n"
            f"   ▲{s.score} · <a href=\"{comments_url}\">{s.descendants}评论</a> · {age} · {s.by}"
        )

    lines.append(
        f"\n<a href=\"https://news.ycombinator.com\">🌐 打开 Hacker News</a>"
        f" · <i>{datetime.now(timezone.utc).strftime('%H:%M UTC')}</i>"
        f"\n<i>/hn more · /hn best · /hn new · /hn ask · /hn show</i>"
    )
    return "\n".join(lines)
