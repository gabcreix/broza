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
from core.models.config import QueryDefinition
from core.models.raw import RawPayload

CONNECTOR_VERSION = "1"
TOP_COMMENT_LIMIT = 10
REDDIT_HOST = "https://www.reddit.com"

# Reddit's edge scores a browser User-Agent that arrives without a real browser TLS
# fingerprint as a lying bot and 403s it; a plain, honest, descriptive UA is treated more
# leniently (this is the path the wider ecosystem uses). Override with REDDIT_USER_AGENT.
DEFAULT_REDDIT_USER_AGENT = "broza/0.1 (content aggregation research)"


class RedditParams(BaseModel):
    subreddit: str
    listing: str = "new"
    limit: int = Field(default=25, le=100)
    # Only meaningful for listing="top"/"controversial": hour|day|week|month|year|all.
    time_filter: str | None = None


@register_connector
class RedditConnector(Connector):
    """Unauthenticated read of Reddit's public ``.json`` endpoints: one request per listing
    for the posts, one per post for its comment tree. Yields one raw payload per post and one
    per top-10 comment; Silver later resolves the post/comment hierarchy from Reddit's own
    ``link_id``/``parent_id``."""

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

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": os.environ.get("REDDIT_USER_AGENT") or DEFAULT_REDDIT_USER_AGENT}

    async def fetch(
        self, query: QueryDefinition | None, since: datetime | None
    ) -> AsyncIterator[RawPayload]:
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=30, follow_redirects=True
        ) as client:
            async for submission in self._listing(client, query):
                created = datetime.fromtimestamp(submission["created_utc"], tz=timezone.utc)
                if since is not None and created <= since:
                    continue

                yield RawPayload(
                    external_id=submission["name"],
                    fetched_at=datetime.now(timezone.utc),
                    connector_version=CONNECTOR_VERSION,
                    payload=_submission_payload(submission),
                )

                async for comment in self._fetch_top_comments(client, submission):
                    yield comment

    async def _listing(
        self, client: httpx.AsyncClient, query: QueryDefinition | None
    ) -> AsyncIterator[dict[str, Any]]:
        params: dict[str, Any] = {"limit": self.params.limit}
        if query and query.definition.natural_language:
            url = f"{REDDIT_HOST}/r/{self.params.subreddit}/search.json"
            params.update(
                {"q": query.definition.natural_language, "restrict_sr": 1, "sort": "new"}
            )
        else:
            url = f"{REDDIT_HOST}/r/{self.params.subreddit}/{self.params.listing}.json"
            if self.params.time_filter:
                params["t"] = self.params.time_filter

        resp = await client.get(url, params=params)
        resp.raise_for_status()
        for child in resp.json()["data"]["children"]:
            if child.get("kind") == "t3":
                yield child["data"]

    async def _fetch_top_comments(
        self, client: httpx.AsyncClient, submission: dict[str, Any]
    ) -> AsyncIterator[RawPayload]:
        url = f"{REDDIT_HOST}/r/{self.params.subreddit}/comments/{submission['id']}.json"
        resp = await client.get(url, params={"limit": 100, "sort": "top"})
        resp.raise_for_status()
        listings = resp.json()
        if len(listings) < 2:
            return

        comments = [
            child["data"]
            for child in listings[1]["data"]["children"]
            if child.get("kind") == "t1"
        ]
        comments.sort(key=lambda c: c.get("score", 0), reverse=True)
        for comment in comments[:TOP_COMMENT_LIMIT]:
            yield RawPayload(
                external_id=comment["name"],
                fetched_at=datetime.now(timezone.utc),
                connector_version=CONNECTOR_VERSION,
                payload=_comment_payload(comment),
            )


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
