#!/usr/bin/env python3
"""XBM — X Bookmarks Manager CLI.

Usage:
    python main.py login      Open browser to log in to X (first time)
    python main.py fetch      Scrape bookmarks from X
    python main.py classify   Classify unclassified bookmarks via LLM
    python main.py run        Fetch + classify in one step
    python main.py stats      Show category statistics
    python main.py export     Export bookmarks to CSV
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict

from rich.console import Console
from rich.table import Table

from config import cfg
from database import BookmarkDB

console = Console()


def _get_db() -> BookmarkDB:
    db = BookmarkDB(cfg.database_path)
    db.init_db()
    return db


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_login(_args: argparse.Namespace) -> None:
    """Open browser for manual X login — saves session for future use."""
    from scraper import login

    login()


def cmd_fetch(args: argparse.Namespace) -> None:
    """Scrape bookmarks from X and store in database."""
    from scraper import fetch_bookmarks

    db = _get_db()
    try:
        bookmarks = fetch_bookmarks(
            db,
            limit=args.limit,
            headless=not args.visible,
        )
        if bookmarks:
            rows = db.upsert_bookmarks([asdict(bm) for bm in bookmarks])
            console.print(f"[green]✓ Stored {rows} bookmarks in database.[/]")
        else:
            console.print("[yellow]No new bookmarks found.[/]")
    finally:
        db.close()


def cmd_classify(_args: argparse.Namespace) -> None:
    """Classify unclassified bookmarks using LLM."""
    from classifier import classify_tweets

    db = _get_db()
    try:
        unclassified = db.get_unclassified()
        if not unclassified:
            console.print("[yellow]All bookmarks are already classified.[/]")
            return

        console.print(f"[cyan]Classifying {len(unclassified)} bookmarks…[/]")
        results = classify_tweets(unclassified)
        updated = db.update_categories(results)
        console.print(f"[green]✓ Classified {updated} bookmarks.[/]")

        _print_stats(db)
    finally:
        db.close()


def cmd_run(args: argparse.Namespace) -> None:
    """Fetch then classify — the full pipeline."""
    cmd_fetch(args)
    cmd_classify(args)


def cmd_stats(_args: argparse.Namespace) -> None:
    """Print category statistics."""
    db = _get_db()
    try:
        _print_stats(db)
    finally:
        db.close()


def cmd_export(args: argparse.Namespace) -> None:
    """Export bookmarks to CSV."""
    db = _get_db()
    try:
        path = db.export_csv(args.output)
        if path:
            console.print(f"[green]✓ Exported to {path}[/]")
        else:
            console.print("[yellow]No bookmarks to export.[/]")
    finally:
        db.close()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _print_stats(db: BookmarkDB) -> None:
    stats = db.get_stats()
    total = stats.pop("_total", 0)

    table = Table(
        title=f"📊 Bookmark Statistics (total: {total})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Category", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Bar", min_width=20)

    max_count = max(stats.values()) if stats else 1
    for cat, count in stats.items():
        bar_len = int((count / max_count) * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        table.add_row(cat, str(count), f"[green]{bar}[/]")

    console.print(table)


# ── CLI ──────────────────────────────────────────────────────────────────────


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="xbm",
        description="XBM — X Bookmarks Manager: scrape, classify, and store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # login
    p_login = sub.add_parser("login", help="Open browser to log in to X")
    p_login.set_defaults(func=cmd_login)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Scrape bookmarks from X")
    p_fetch.add_argument(
        "-n", "--limit", type=int, default=None, help="Max bookmarks to fetch"
    )
    p_fetch.add_argument(
        "--visible", action="store_true", help="Show browser window while scraping"
    )
    p_fetch.set_defaults(func=cmd_fetch)

    # classify
    p_classify = sub.add_parser("classify", help="Classify unclassified bookmarks")
    p_classify.set_defaults(func=cmd_classify)

    # run
    p_run = sub.add_parser("run", help="Fetch + classify (full pipeline)")
    p_run.add_argument(
        "-n", "--limit", type=int, default=None, help="Max bookmarks to fetch"
    )
    p_run.add_argument(
        "--visible", action="store_true", help="Show browser window while scraping"
    )
    p_run.set_defaults(func=cmd_run)

    # stats
    p_stats = sub.add_parser("stats", help="Show statistics")
    p_stats.set_defaults(func=cmd_stats)

    # export
    p_export = sub.add_parser("export", help="Export bookmarks to CSV")
    p_export.add_argument(
        "-o", "--output", default="bookmarks_export.csv", help="Output CSV path"
    )
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    cli()
