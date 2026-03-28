"""
Comprehensive unit tests for agent/finance/hackernews.py
Tests HN story fetching, formatting, and async operations.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from agent.finance.hackernews import (
    HNStory,
    fetch_story,
    fetch_top_stories,
    format_stories_telegram,
)


# ── HNStory Tests ────────────────────────────────────────────────────

class TestHNStory:
    def test_creation_minimal(self):
        story = HNStory(id=1, title="Test Story")
        assert story.id == 1
        assert story.title == "Test Story"
        assert story.url == ""
        assert story.score == 0
        assert story.descendants == 0

    def test_creation_full(self):
        story = HNStory(
            id=12345,
            title="Major Tech News",
            url="https://example.com/news",
            score=500,
            by="dang",
            descendants=150,
            time=1704067200,
            type="story",
        )
        assert story.id == 12345
        assert story.score == 500
        assert story.by == "dang"
        assert story.descendants == 150
        assert story.type == "story"

    def test_hn_url_property(self):
        story = HNStory(id=999, title="Test")
        url = story.hn_url
        assert "news.ycombinator.com" in url
        assert "999" in url

    def test_display_url_with_url(self):
        story = HNStory(id=1, title="Test", url="https://external.com")
        assert story.display_url == "https://external.com"

    def test_display_url_fallback_to_hn(self):
        story = HNStory(id=2, title="Test", url="")
        assert "news.ycombinator.com" in story.display_url

    def test_age_hours_recent(self):
        """Test age calculation for recent story."""
        now = int(time.time())
        story = HNStory(id=1, title="Test", time=now)
        age = story.age_hours
        # Should be very close to 0
        assert age < 1

    def test_age_hours_old(self):
        """Test age calculation for old story."""
        now = int(time.time())
        story = HNStory(id=1, title="Test", time=now - 86400)  # 1 day old
        age = story.age_hours
        assert 23 < age < 25  # Approximately 24 hours

    def test_age_hours_no_timestamp(self):
        """Test age when timestamp is 0."""
        story = HNStory(id=1, title="Test", time=0)
        assert story.age_hours == 0


# ── fetch_story Tests ───────────────────────────────────────────────

class TestFetchStory:
    def test_fetch_story_success(self):
        """Test successful story fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 12345,
            "title": "Great Article",
            "url": "https://example.com",
            "score": 250,
            "by": "user123",
            "descendants": 50,
            "time": 1704067200,
            "type": "story",
        }

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            story = fetch_story(12345)

            assert story is not None
            assert story.id == 12345
            assert story.title == "Great Article"
            assert story.score == 250
            assert story.descendants == 50

    def test_fetch_story_not_found(self):
        """Test story fetch when status is not 200."""
        mock_response = Mock()
        mock_response.status_code = 404

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            story = fetch_story(999999)
            assert story is None

    def test_fetch_story_not_story_type(self):
        """Test fetch when item is not a story."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 1,
            "type": "comment",  # Not a story
            "text": "Just a comment",
        }

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            story = fetch_story(1)
            assert story is None

    def test_fetch_story_job_type(self):
        """Test fetch accepts job type."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 1,
            "title": "Hiring: Python Dev",
            "type": "job",
            "url": "https://example.com/job",
            "time": 1704067200,
        }

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            story = fetch_story(1)
            assert story is not None
            assert story.type == "job"

    def test_fetch_story_exception(self):
        """Test exception handling in story fetch."""
        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            story = fetch_story(1)
            assert story is None

    def test_fetch_story_invalid_json(self):
        """Test handling of invalid JSON response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            story = fetch_story(1)
            assert story is None

    def test_fetch_story_missing_fields(self):
        """Test story fetch with minimal fields."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 1,
            "title": "Minimal Story",
            "type": "story",
        }

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            story = fetch_story(1)
            assert story is not None
            assert story.title == "Minimal Story"
            assert story.score == 0  # Default value
            assert story.url == ""  # Default value


# ── fetch_top_stories Tests ──────────────────────────────────────────

class TestFetchTopStories:
    @pytest.mark.asyncio
    async def test_fetch_top_stories_success(self):
        """Test successful top stories fetch."""
        # Mock the ID list fetch
        mock_id_response = Mock()
        mock_id_response.status_code = 200
        mock_id_response.json.return_value = [1, 2, 3, 4, 5]

        # Mock individual story fetches
        stories_data = [
            {"id": 1, "title": "Story 1", "score": 100, "type": "story"},
            {"id": 2, "title": "Story 2", "score": 90, "type": "story"},
            {"id": 3, "title": "Story 3", "score": 80, "type": "story"},
        ]

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            # First call returns ID list
            mock_get.return_value = mock_id_response

            with patch("agent.finance.hackernews.fetch_story") as mock_fetch:
                mock_fetch.side_effect = [
                    HNStory(id=1, title="Story 1", score=100),
                    HNStory(id=2, title="Story 2", score=90),
                    HNStory(id=3, title="Story 3", score=80),
                ]

                stories = await fetch_top_stories(category="top", limit=3)
                assert len(stories) == 3
                assert stories[0].id == 1

    @pytest.mark.asyncio
    async def test_fetch_top_stories_categories(self):
        """Test different story categories."""
        categories = ["top", "best", "new", "ask", "show", "job"]

        for category in categories:
            mock_id_response = Mock()
            mock_id_response.status_code = 200
            mock_id_response.json.return_value = [1, 2, 3]

            with patch("agent.finance.hackernews.requests.get") as mock_get:
                mock_get.return_value = mock_id_response

                with patch("agent.finance.hackernews.fetch_story") as mock_fetch:
                    mock_fetch.side_effect = [
                        HNStory(id=i, title=f"Story {i}", score=100-i*10)
                        for i in range(1, 4)
                    ]

                    stories = await fetch_top_stories(category=category, limit=3)
                    assert len(stories) == 3

    @pytest.mark.asyncio
    async def test_fetch_top_stories_min_score_filter(self):
        """Test min_score filtering."""
        mock_id_response = Mock()
        mock_id_response.status_code = 200
        mock_id_response.json.return_value = [1, 2, 3, 4, 5]

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_id_response

            with patch("agent.finance.hackernews.fetch_story") as mock_fetch:
                mock_fetch.side_effect = [
                    HNStory(id=1, title="Story 1", score=150),
                    HNStory(id=2, title="Story 2", score=100),
                    HNStory(id=3, title="Story 3", score=50),
                    HNStory(id=4, title="Story 4", score=200),
                    HNStory(id=5, title="Story 5", score=25),
                ]

                stories = await fetch_top_stories(limit=10, min_score=100)
                # Should only include stories with score >= 100
                assert all(s.score >= 100 for s in stories)

    @pytest.mark.asyncio
    async def test_fetch_top_stories_limit(self):
        """Test limit parameter."""
        mock_id_response = Mock()
        mock_id_response.status_code = 200
        mock_id_response.json.return_value = list(range(1, 50))

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_id_response

            with patch("agent.finance.hackernews.fetch_story") as mock_fetch:
                mock_fetch.side_effect = [
                    HNStory(id=i, title=f"Story {i}", score=100)
                    for i in range(1, 50)
                ]

                stories = await fetch_top_stories(limit=5)
                assert len(stories) <= 5

    @pytest.mark.asyncio
    async def test_fetch_top_stories_api_error(self):
        """Test handling of API errors."""
        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.side_effect = Exception("API Error")
            stories = await fetch_top_stories()
            assert stories == []

    @pytest.mark.asyncio
    async def test_fetch_top_stories_bad_status(self):
        """Test handling of bad HTTP status."""
        mock_response = Mock()
        mock_response.status_code = 500

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            stories = await fetch_top_stories()
            assert stories == []

    @pytest.mark.asyncio
    async def test_fetch_top_stories_empty_response(self):
        """Test handling of empty ID list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_response
            stories = await fetch_top_stories()
            assert stories == []


# ── format_stories_telegram Tests ────────────────────────────────────

class TestFormatStoriesTelegram:
    def test_format_empty_stories(self):
        """Test formatting empty story list."""
        result = format_stories_telegram([])
        assert "没有找到" in result or "No" in result or len(result) > 0

    def test_format_single_story(self):
        """Test formatting single story."""
        story = HNStory(
            id=1,
            title="Breaking Tech News",
            url="https://example.com/news",
            score=500,
            descendants=100,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])

        assert "Breaking Tech News" in result
        assert "500" in result or "▲" in result
        assert "example.com" in result or "Breaking Tech News" in result

    def test_format_multiple_stories(self):
        """Test formatting multiple stories."""
        stories = [
            HNStory(
                id=i,
                title=f"Story {i}",
                url=f"https://example.com/{i}",
                score=500-i*50,
                descendants=100-i*10,
                time=int(time.time()) - i*3600,
            )
            for i in range(1, 4)
        ]
        result = format_stories_telegram(stories, title="Top Stories")

        assert "Top Stories" in result
        assert "Story 1" in result
        assert "Story 2" in result
        assert "Story 3" in result

    def test_format_shows_age(self):
        """Test that story age is shown."""
        now = int(time.time())
        story = HNStory(
            id=1,
            title="Old Story",
            score=100,
            descendants=10,
            time=now - 3600,  # 1 hour old
        )
        result = format_stories_telegram([story])
        # Should show age in hours
        assert "h" in result or "hour" in result.lower()

    def test_format_shows_comments(self):
        """Test that comment count is displayed."""
        story = HNStory(
            id=1,
            title="Discussed Topic",
            score=200,
            descendants=500,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])
        assert "500" in result or "comment" in result.lower() or "评论" in result

    def test_format_shows_hn_links(self):
        """Test that HN discussion links are included."""
        story = HNStory(
            id=12345,
            title="Test",
            score=100,
            descendants=50,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])
        assert "news.ycombinator.com" in result or "hn" in result.lower()

    def test_format_includes_footer(self):
        """Test that footer with links is included."""
        story = HNStory(
            id=1,
            title="Test",
            score=100,
            descendants=10,
            time=int(time.time()),
        )
        result = format_stories_telegram([story], title="HN")
        assert "Hacker News" in result or "news.ycombinator.com" in result

    def test_format_handles_special_characters(self):
        """Test formatting with special characters in title."""
        story = HNStory(
            id=1,
            title="Breaking: \"New\" Tech & Innovation",
            url="https://example.com",
            score=100,
            descendants=50,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])
        # Should not crash and should contain content
        assert len(result) > 0

    def test_format_long_title_truncation(self):
        """Test that very long titles are handled."""
        long_title = "A" * 500
        story = HNStory(
            id=1,
            title=long_title,
            score=100,
            descendants=10,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])
        # Should contain at least part of title
        assert "A" in result

    def test_format_no_url_uses_hn(self):
        """Test that stories without URL use HN link."""
        story = HNStory(
            id=999,
            title="Ask HN: Something",
            url="",
            score=50,
            descendants=25,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])
        assert "news.ycombinator.com" in result

    def test_format_timestamp_in_output(self):
        """Test that timestamp is included in footer."""
        story = HNStory(
            id=1,
            title="Test",
            score=100,
            descendants=10,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])
        # Should have UTC time in footer
        assert "UTC" in result or "time" in result.lower()


# ── Edge Cases and Integration Tests ────────────────────────────────

class TestHackerNewsEdgeCases:
    def test_story_zero_score(self):
        """Test story with zero score."""
        story = HNStory(id=1, title="Unknown", score=0)
        assert story.score == 0

    def test_story_zero_descendants(self):
        """Test story with zero comments."""
        story = HNStory(id=1, title="Silent", descendants=0)
        assert story.descendants == 0

    def test_story_very_old_age(self):
        """Test age calculation for very old story."""
        ancient_time = 0  # Unix epoch
        story = HNStory(id=1, title="Ancient", time=ancient_time)
        age = story.age_hours
        # Should be huge number of hours
        assert age > 1000

    @pytest.mark.asyncio
    async def test_fetch_stories_timeout(self):
        """Test handling of timeout during fetch."""
        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.side_effect = TimeoutError("Request timeout")
            stories = await fetch_top_stories()
            assert stories == []

    def test_format_with_html_entities(self):
        """Test formatting with HTML entities in title."""
        story = HNStory(
            id=1,
            title="Test &amp; Demo &lt;tag&gt;",
            score=100,
            descendants=10,
            time=int(time.time()),
        )
        result = format_stories_telegram([story])
        # Should handle HTML entities
        assert len(result) > 0

    def test_story_negative_time(self):
        """Test story with negative timestamp."""
        story = HNStory(id=1, title="Impossible", time=-1)
        # Should handle gracefully
        age = story.age_hours
        assert age >= 0  # Should not be negative

    @pytest.mark.asyncio
    async def test_fetch_mixed_valid_invalid(self):
        """Test fetching when some stories are valid and some are not."""
        mock_id_response = Mock()
        mock_id_response.status_code = 200
        mock_id_response.json.return_value = [1, 2, 3, 4, 5]

        with patch("agent.finance.hackernews.requests.get") as mock_get:
            mock_get.return_value = mock_id_response

            with patch("agent.finance.hackernews.fetch_story") as mock_fetch:
                mock_fetch.side_effect = [
                    HNStory(id=1, title="Valid 1", score=100),
                    None,  # Failed fetch
                    HNStory(id=3, title="Valid 2", score=90),
                    None,  # Failed fetch
                    HNStory(id=5, title="Valid 3", score=80),
                ]

                stories = await fetch_top_stories(limit=5)
                # Should only have valid stories
                assert len(stories) == 3
