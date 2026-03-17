"""LLM-based tweet classifier using OpenAI-compatible API."""

from __future__ import annotations

import json
import re
from textwrap import dedent

from openai import OpenAI
from rich.console import Console

from config import cfg

console = Console()

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
        )
    return _client


SYSTEM_PROMPT = dedent("""\
    You are a tweet classifier. Given a list of tweets, assign each tweet
    exactly ONE category from the following list:

    {categories}

    Rules:
    - Respond ONLY with valid JSON — an array of objects.
    - Each object must have "id" (string) and "category" (string).
    - The "category" MUST be one of the categories listed above.
    - If a tweet could belong to multiple categories, choose the most dominant one.
    - If unsure, use "Other".

    Example response:
    [
      {{"id": "123", "category": "Tech"}},
      {{"id": "456", "category": "Life"}}
    ]
""")

BATCH_SIZE = 15  # tweets per API call to stay within context limits


def _build_user_prompt(tweets: list[dict]) -> str:
    """Build the user message with tweet texts."""
    lines = []
    for t in tweets:
        text_preview = t["text"][:300].replace("\n", " ")
        lines.append(f'[{t["id"]}] {text_preview}')
    return "\n".join(lines)


def _parse_response(content: str) -> list[dict]:
    """Extract JSON array from LLM response, handling markdown code fences."""
    # Strip markdown code fences if present
    content = content.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
    if match:
        content = match.group(1).strip()

    try:
        result = json.loads(content)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try to find JSON array in the response
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return []


def classify_tweets(
    tweets: list[dict],
    *,
    batch_size: int = BATCH_SIZE,
) -> dict[str, str]:
    """
    Classify a list of tweets using the LLM.

    Parameters
    ----------
    tweets : list[dict]
        Each dict must have at least ``id`` and ``text`` keys.
    batch_size : int
        Number of tweets per LLM call.

    Returns
    -------
    dict[str, str]
        Mapping of tweet_id → category.
    """
    client = _get_client()
    categories_str = ", ".join(cfg.categories)
    system = SYSTEM_PROMPT.format(categories=categories_str)

    results: dict[str, str] = {}
    valid_categories = set(cfg.categories)

    for i in range(0, len(tweets), batch_size):
        batch = tweets[i : i + batch_size]
        user_prompt = _build_user_prompt(batch)

        try:
            resp = client.chat.completions.create(
                model=cfg.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            content = resp.choices[0].message.content or ""
            parsed = _parse_response(content)

            for item in parsed:
                tid = str(item.get("id", ""))
                cat = item.get("category", "Other")
                if cat not in valid_categories:
                    cat = "Other"
                results[tid] = cat

        except Exception as exc:
            console.print(f"[red]Classification error for batch {i // batch_size + 1}: {exc}[/]")
            # fallback: mark all in this batch as Other
            for t in batch:
                results[t["id"]] = "Other"

        console.print(
            f"[dim]  Classified batch {i // batch_size + 1}"
            f" ({len(batch)} tweets)[/]"
        )

    # Ensure every tweet has a result
    for t in tweets:
        results.setdefault(t["id"], "Other")

    return results
