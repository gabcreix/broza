from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import Page
from pydantic import BaseModel, Field

from core.connectors.base import (
    AcquisitionMethod,
    Connector,
    ConnectorCapabilities,
    register_connector,
)
from core.connectors.browser import browser_page, fetch_json
from core.models.config import QueryDefinition
from core.models.raw import RawPayload

CONNECTOR_VERSION = "1"
TOP_COMMENT_LIMIT = 10
REDDIT_HOST = "https://www.reddit.com"


class RedditParams(BaseModel):
    subreddit: str
    listing: str = "new"
    limit: int = Field(default=25, le=100)
    # Only meaningful for listing="top"/"controversial": hour|day|week|month|year|all.
    time_filter: str | None = None


@register_connector
class RedditConnector(Connector):
    """Read of Reddit's public ``.json`` endpoints through a real browser (Playwright).

    Plain HTTP clients get 403'd at Cloudflare's edge regardless of User-Agent; a real
    Chromium clears the challenge once and then serves the JSON. One request per listing for
    the posts, one per post for its comment tree; top-10 comments by score as separate raw
    payloads. Silver later resolves the post/comment hierarchy from Reddit's ``link_id``/
    ``parent_id``.

    The browser work is synchronous and runs in a worker thread (see browser.py for why), so
    `fetch` collects everything off-thread and then streams the payloads.
    """

    type = "reddit"
    display_name = "Reddit"
    capabilities = ConnectorCapabilities(
        keyword_search=True, date_filter=False, native_categories=False, pagination=True
    )
    acquisition = [AcquisitionMethod.SCRAPING]
    param_model = RedditParams

    @property
    def params(self) -> RedditParams:
        return RedditParams.model_validate(self.source.params)

    async def fetch(
        self, query: QueryDefinition | None, since: datetime | None
    ) -> AsyncIterator[RawPayload]:
        payloads = await asyncio.to_thread(self._scrape, query, since)
        for external_id, payload in payloads:
            yield RawPayload(
                external_id=external_id,
                fetched_at=datetime.now(timezone.utc),
                connector_version=CONNECTOR_VERSION,
                payload=payload,
            )

    def _scrape(
        self, query: QueryDefinition | None, since: datetime | None
    ) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        with browser_page(f"{REDDIT_HOST}/r/{self.params.subreddit}/") as page:
            listing = fetch_json(page, *self._listing_request(query))

            for child in listing["data"]["children"]:
                if child.get("kind") != "t3":
                    continue
                submission = child["data"]

                created = datetime.fromtimestamp(submission["created_utc"], tz=timezone.utc)
                if since is not None and created <= since:
                    continue

                out.append((submission["name"], _submission_payload(submission)))
                for comment in self._top_comments(page, submission["id"]):
                    out.append((comment["name"], _comment_payload(comment)))
        return out

    def _listing_request(self, query: QueryDefinition | None) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {"limit": self.params.limit}
        if query and query.definition.natural_language:
            params.update(
                {"q": query.definition.natural_language, "restrict_sr": 1, "sort": "new"}
            )
            return f"{REDDIT_HOST}/r/{self.params.subreddit}/search.json", params
        if self.params.time_filter:
            params["t"] = self.params.time_filter
        return f"{REDDIT_HOST}/r/{self.params.subreddit}/{self.params.listing}.json", params

    def _top_comments(self, page: Page, post_id: str) -> list[dict[str, Any]]:
        url = f"{REDDIT_HOST}/r/{self.params.subreddit}/comments/{post_id}.json"
        listings = fetch_json(page, url, {"limit": 100, "sort": "top"})
        if len(listings) < 2:
            return []
        comments = [
            child["data"]
            for child in listings[1]["data"]["children"]
            if child.get("kind") == "t1"
        ]
        comments.sort(key=lambda c: c.get("score", 0), reverse=True)
        return comments[:TOP_COMMENT_LIMIT]


def _submission_payload(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": s.get("name"),
        "id": s.get("id"),
        "created_utc": s.get("created_utc"),
        "title": s.get("title"),
        "selftext": s.get("selftext"),
        "author": s.get("author"),
        "score": s.get("score"),
        "num_comments": s.get("num_comments"),
        "permalink": s.get("permalink"),
        "url": s.get("url"),
    }


def _comment_payload(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": c.get("name"),
        "id": c.get("id"),
        "body": c.get("body"),
        "author": c.get("author"),
        "score": c.get("score"),
        "created_utc": c.get("created_utc"),
        "link_id": c.get("link_id"),
        "parent_id": c.get("parent_id"),
    }
