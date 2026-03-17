"""Bookmark scraper — uses Playwright to capture X's internal GraphQL API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, Page, BrowserContext, Response
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import cfg
from database import BookmarkDB

console = Console()

BOOKMARKS_URL = "https://x.com/i/bookmarks"
GRAPHQL_BOOKMARK_PATTERN = "**/i/api/graphql/**/Bookmarks*"


@dataclass
class Bookmark:
    """Normalised bookmark record."""

    id: str
    text: str
    author_id: str = ""
    author_name: str = ""
    author_username: str = ""
    created_at: str | None = None
    url: str = ""
    raw_json: str = ""
    category: str = "Other"


# ── GraphQL response parsing ────────────────────────────────────────────────


def _extract_tweets_from_graphql(data: dict) -> list[dict[str, Any]]:
    """Recursively extract tweet entries from the GraphQL response."""
    tweets: list[dict[str, Any]] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            # Check if this is a tweet result
            if obj.get("__typename") == "Tweet":
                tweets.append(obj)
            elif "tweet_results" in obj:
                result = obj["tweet_results"].get("result", {})
                if result.get("__typename") == "Tweet":
                    tweets.append(result)
                elif result.get("__typename") == "TweetWithVisibilityResults":
                    inner = result.get("tweet", {})
                    if inner:
                        tweets.append(inner)
            # Also check for timeline entries pattern
            elif "itemContent" in obj:
                item = obj["itemContent"]
                if item.get("itemType") == "TimelineTweet":
                    result = item.get("tweet_results", {}).get("result", {})
                    if result.get("__typename") == "Tweet":
                        tweets.append(result)
                    elif result.get("__typename") == "TweetWithVisibilityResults":
                        inner = result.get("tweet", {})
                        if inner:
                            tweets.append(inner)
                return  # Don't recurse further into already processed items

            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return tweets


def _parse_tweet(tweet_data: dict) -> Bookmark | None:
    """Parse a single tweet object from GraphQL into a Bookmark."""
    try:
        legacy = tweet_data.get("legacy", {})
        core = tweet_data.get("core", {})
        user_results = core.get("user_results", {}).get("result", {})
        user_legacy = user_results.get("legacy", {})

        tweet_id = legacy.get("id_str") or tweet_data.get("rest_id", "")
        if not tweet_id:
            return None

        text = legacy.get("full_text", "")
        author_id = user_results.get("rest_id", "")
        author_name = user_legacy.get("name", "")
        author_username = user_legacy.get("screen_name", "")
        created_at = legacy.get("created_at", "")

        url = (
            f"https://x.com/{author_username}/status/{tweet_id}"
            if author_username
            else f"https://x.com/i/status/{tweet_id}"
        )

        return Bookmark(
            id=tweet_id,
            text=text,
            author_id=author_id,
            author_name=author_name,
            author_username=author_username,
            created_at=created_at,
            url=url,
            raw_json=json.dumps(tweet_data, default=str, ensure_ascii=False),
        )
    except Exception as exc:
        console.print(f"[dim red]Failed to parse tweet: {exc}[/]")
        return None


# ── Browser session ─────────────────────────────────────────────────────────


def _ensure_browser_data_dir() -> Path:
    path = cfg.browser_data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def login() -> None:
    """Open a browser window for the user to log in to X manually.

    The session is persisted to ``browser_data/`` for future use.
    """
    data_dir = _ensure_browser_data_dir()
    console.print("[bold cyan]Opening browser — please log in to X…[/]")
    console.print("[dim]After logging in, close the browser window to save your session.[/]")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(data_dir),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://x.com/login", wait_until="domcontentloaded")

        console.print("[yellow]Waiting for you to log in… Close the browser when done.[/]")
        # Wait until the browser is closed by the user
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        context.close()

    console.print("[green]✓ Session saved. You can now use 'fetch' without logging in again.[/]")


def fetch_bookmarks(
    db: BookmarkDB,
    *,
    limit: int | None = None,
    headless: bool = True,
    scroll_pause: float = 2.0,
    max_no_new_scrolls: int = 5,
) -> list[Bookmark]:
    """Scrape bookmarks from X using Playwright.

    Parameters
    ----------
    db : BookmarkDB
        Database instance (used to check existing IDs).
    limit : int | None
        Max number of new bookmarks to collect. None = unlimited.
    headless : bool
        Run browser in headless mode.
    scroll_pause : float
        Seconds to wait between scrolls.
    max_no_new_scrolls : int
        Stop after this many consecutive scrolls with no new bookmarks.

    Returns
    -------
    list[Bookmark]
        List of newly discovered bookmarks.
    """
    data_dir = _ensure_browser_data_dir()
    if not (data_dir / "Default").exists() and not any(data_dir.iterdir()):
        console.print("[red]No saved session found. Please run 'login' first.[/]")
        return []

    existing_ids = db.get_existing_ids()
    collected: dict[str, Bookmark] = {}  # tweet_id → Bookmark (deduped)
    graphql_responses: list[dict] = []

    def _on_response(response: Response) -> None:
        """Capture bookmark GraphQL responses."""
        try:
            url = response.url
            if "/i/api/graphql/" in url and "Bookmark" in url:
                if response.status == 200:
                    data = response.json()
                    graphql_responses.append(data)
        except Exception:
            pass

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(data_dir),
            channel="chrome",
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", _on_response)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Loading bookmarks page…", total=None)

            # Navigate to bookmarks
            page.goto(BOOKMARKS_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # Wait for initial GraphQL to fire

            # Check if we need to log in
            if "login" in page.url.lower():
                console.print("[red]Not logged in! Please run 'login' first.[/]")
                context.close()
                return []

            no_new_count = 0
            prev_count = 0

            while True:
                # Process any captured GraphQL responses
                while graphql_responses:
                    resp_data = graphql_responses.pop(0)
                    raw_tweets = _extract_tweets_from_graphql(resp_data)
                    for raw in raw_tweets:
                        bm = _parse_tweet(raw)
                        if bm and bm.id not in collected and bm.id not in existing_ids:
                            collected[bm.id] = bm

                progress.update(
                    task,
                    description=f"Scraping bookmarks… found {len(collected)} new",
                )

                # Check limits
                if limit and len(collected) >= limit:
                    break

                # Scroll down to trigger more loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(int(scroll_pause * 1000))

                # Check if we got new bookmarks
                if len(collected) == prev_count:
                    no_new_count += 1
                    if no_new_count >= max_no_new_scrolls:
                        break
                else:
                    no_new_count = 0
                    prev_count = len(collected)

            # Process any remaining responses
            while graphql_responses:
                resp_data = graphql_responses.pop(0)
                raw_tweets = _extract_tweets_from_graphql(resp_data)
                for raw in raw_tweets:
                    bm = _parse_tweet(raw)
                    if bm and bm.id not in collected and bm.id not in existing_ids:
                        collected[bm.id] = bm

        context.close()

    result = list(collected.values())
    if limit:
        result = result[:limit]

    console.print(f"[green]✓ Found {len(result)} new bookmarks.[/]")
    return result
