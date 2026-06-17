from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import asyncpraw
from pydantic import BaseModel, Field

from core.connectors.base import (
    AcquisitionMethod,
    Connector,
    ConnectorCapabilities,
    register_connector,
)
from core.connectors.http import DEFAULT_USER_AGENT
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
    """Official API (OAuth, app-only via AsyncPRAW) — unauthenticated scraping of Reddit's
    .json endpoints is blocked at the edge regardless of User-Agent/IP, so this is the only
    viable acquisition path. Yields one raw payload per post and one per top-10 comment;
    Silver later resolves the post/comment parent_id from Reddit's own link_id/parent_id."""

    type = "reddit"
    display_name = "Reddit"
    capabilities = ConnectorCapabilities(
        keyword_search=True, date_filter=False, native_categories=False, pagination=True
    )
    acquisition = [AcquisitionMethod.API]
    param_model = RedditParams

    @property
    def params(self) -> RedditParams:
        return RedditParams.model_validate(self.source.params)

    async def fetch(
        self, query: QueryDefinition | None, since: datetime | None
    ) -> AsyncIterator[RawPayload]:
        async with asyncpraw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ.get("REDDIT_USER_AGENT") or DEFAULT_USER_AGENT,
        ) as reddit:
            subreddit = await reddit.subreddit(self.params.subreddit)
            listing = self._listing(subreddit, query)

            async for submission in listing:
                created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
                if since is not None and created <= since:
                    continue

                yield RawPayload(
                    external_id=submission.fullname,
                    fetched_at=datetime.now(timezone.utc),
                    connector_version=CONNECTOR_VERSION,
                    payload=_submission_payload(submission),
                )

                async for comment in self._fetch_top_comments(submission):
                    yield comment

    def _listing(self, subreddit: Any, query: QueryDefinition | None) -> Any:
        if query and query.definition.natural_language:
            return subreddit.search(
                query.definition.natural_language, sort="new", limit=self.params.limit
            )
        return getattr(subreddit, self.params.listing)(limit=self.params.limit)

    async def _fetch_top_comments(self, submission: Any) -> AsyncIterator[RawPayload]:
        await submission.comments.replace_more(limit=0)
        comments = sorted(submission.comments, key=lambda c: c.score, reverse=True)
        for comment in comments[:TOP_COMMENT_LIMIT]:
            yield RawPayload(
                external_id=comment.fullname,
                fetched_at=datetime.now(timezone.utc),
                connector_version=CONNECTOR_VERSION,
                payload=_comment_payload(comment),
            )


def _submission_payload(submission: Any) -> dict[str, Any]:
    return {
        "name": submission.fullname,
        "id": submission.id,
        "created_utc": submission.created_utc,
        "title": submission.title,
        "selftext": submission.selftext,
        "author": str(submission.author) if submission.author else None,
        "score": submission.score,
        "num_comments": submission.num_comments,
        "permalink": submission.permalink,
        "url": submission.url,
    }


def _comment_payload(comment: Any) -> dict[str, Any]:
    return {
        "name": comment.fullname,
        "id": comment.id,
        "body": comment.body,
        "author": str(comment.author) if comment.author else None,
        "score": comment.score,
        "created_utc": comment.created_utc,
        "link_id": comment.link_id,
        "parent_id": comment.parent_id,
    }
