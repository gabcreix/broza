from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field

from core.connectors.base import (
    AcquisitionMethod,
    Connector,
    ConnectorCapabilities,
    register_connector,
)
from core.connectors.http import DEFAULT_USER_AGENT, browser_headers
from core.models.config import QueryDefinition
from core.models.raw import RawPayload

CONNECTOR_VERSION = "1"
TOP_COMMENT_LIMIT = 10


class RedditParams(BaseModel):
    subreddit: str
    listing: str = "new"
    limit: int = Field(default=25, le=100)


@register_connector
class RedditConnector(Connector):
    """Public JSON endpoints (no OAuth) — scraping was chosen over praw/the official API
    for v1. Yields one raw payload per post and one per top-10 comment; Silver later
    resolves the post/comment parent_id from Reddit's own link_id/parent_id fields."""

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
        user_agent = os.environ.get("REDDIT_USER_AGENT") or DEFAULT_USER_AGENT
        async with httpx.AsyncClient(headers=browser_headers(user_agent), timeout=30) as client:
            listing_url, listing_params = self._listing_request(query)
            resp = await client.get(listing_url, params=listing_params)
            resp.raise_for_status()
            posts = resp.json()["data"]["children"]

            for post in posts:
                post_data = post["data"]
                created = datetime.fromtimestamp(post_data["created_utc"], tz=timezone.utc)
                if since is not None and created <= since:
                    continue

                yield RawPayload(
                    external_id=post_data["name"],
                    fetched_at=datetime.now(timezone.utc),
                    connector_version=CONNECTOR_VERSION,
                    payload=post_data,
                )

                async for comment in self._fetch_top_comments(client, post_data):
                    yield comment

    def _listing_request(self, query: QueryDefinition | None) -> tuple[str, dict[str, Any]]:
        base = f"https://www.reddit.com/r/{self.params.subreddit}"
        if query and query.definition.natural_language:
            return f"{base}/search.json", {
                "q": query.definition.natural_language,
                "restrict_sr": 1,
                "sort": "new",
                "limit": self.params.limit,
            }
        return f"{base}/{self.params.listing}.json", {"limit": self.params.limit}

    async def _fetch_top_comments(
        self, client: httpx.AsyncClient, post_data: dict[str, Any]
    ) -> AsyncIterator[RawPayload]:
        url = f"https://www.reddit.com/r/{self.params.subreddit}/comments/{post_data['id']}.json"
        resp = await client.get(url, params={"limit": TOP_COMMENT_LIMIT, "sort": "top"})
        resp.raise_for_status()
        _, comments_listing = resp.json()
        comments = [
            c["data"] for c in comments_listing["data"]["children"] if c["kind"] == "t1"
        ][:TOP_COMMENT_LIMIT]

        for comment in comments:
            yield RawPayload(
                external_id=comment["name"],
                fetched_at=datetime.now(timezone.utc),
                connector_version=CONNECTOR_VERSION,
                payload=comment,
            )
