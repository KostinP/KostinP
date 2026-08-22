#!/usr/bin/env python3
"""Self-hosted replacement for the third-party GitHub-streak badges.

Those services proxy through Camo, and the shared public instances are
overloaded enough that Camo's fetch regularly times out (504), leaving a
blank image in the README. This fetches the same contribution-calendar
data straight from GitHub's GraphQL API and renders a static SVG that we
commit into the repo, so the README just points at ./assets/streak.svg
(served directly by GitHub, no third-party fetch involved).

Usage: GITHUB_TOKEN=... GITHUB_LOGIN=KostinP python3 scripts/streak.py
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.request

GRAPHQL_URL = "https://api.github.com/graphql"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "streak.svg")

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    createdAt
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def graphql(token: str, login: str, frm: datetime.datetime, to: datetime.datetime) -> dict:
    payload = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "login": login,
                "from": frm.isoformat() + "Z",
                "to": to.isoformat() + "Z",
            },
        }
    ).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "kostinp-streak-badge",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch_all_days(token: str, login: str) -> tuple[list[tuple[datetime.date, int]], datetime.date]:
    """GraphQL only allows ~1 year per query, so walk year-by-year from account creation."""
    first = graphql(
        token,
        login,
        datetime.datetime(2008, 1, 1),
        datetime.datetime(2008, 1, 2),
    )
    created_at = datetime.datetime.fromisoformat(
        first["user"]["createdAt"].replace("Z", "+00:00")
    ).date()

    days: list[tuple[datetime.date, int]] = []
    window_start = datetime.datetime(created_at.year, created_at.month, created_at.day)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    while window_start < now:
        window_end = min(window_start + datetime.timedelta(days=365), now)
        data = graphql(token, login, window_start, window_end)
        calendar = data["user"]["contributionsCollection"]["contributionCalendar"]
        for week in calendar["weeks"]:
            for day in week["contributionDays"]:
                days.append((datetime.date.fromisoformat(day["date"]), day["contributionCount"]))
        window_start = window_end

    # de-dupe (window edges overlap by a day) and sort chronologically
    by_date = {d: c for d, c in days}
    ordered = sorted(by_date.items())
    return ordered, created_at


def compute_stats(days: list[tuple[datetime.date, int]]):
    total = sum(c for _, c in days)

    best_len, best_range = 0, None
    run_len, run_start = 0, None
    for date, count in days:
        if count > 0:
            if run_len == 0:
                run_start = date
            run_len += 1
            if run_len > best_len:
                best_len = run_len
                best_range = (run_start, date)
        else:
            run_len = 0

    # current streak: walk backwards from the most recent day that has data
    cur_len, cur_range = 0, None
    for date, count in reversed(days):
        if count > 0:
            if cur_len == 0:
                cur_range = [date, date]
            cur_len += 1
            cur_range[0] = date
        else:
            # allow "today" to be a gap (no contributions yet) without breaking the streak
            if date == days[-1][0]:
                continue
            break

    return {
        "total": total,
        "current_len": cur_len,
        "current_range": tuple(cur_range) if cur_range else None,
        "best_len": best_len,
        "best_range": best_range,
    }


def fmt_range(rng) -> str:
    if not rng:
        return "—"
    start, end = rng
    fmt = lambda d: d.strftime("%d.%m.%y")
    return fmt(start) if start == end else f"{fmt(start)} – {fmt(end)}"


def render_svg(stats: dict, login: str, created_at: datetime.date) -> str:
    bg = "#1A1B27"
    border = "#30334066"
    accent = "#6366F1"
    fg = "#E4E2E2"
    muted = "#8B8FA3"

    columns = [
        ("Всего вкладов", str(stats["total"]), f"с {created_at.year}"),
        ("Текущий стрик", f"{stats['current_len']} дн.", fmt_range(stats["current_range"])),
        ("Лучший стрик", f"{stats['best_len']} дн.", fmt_range(stats["best_range"])),
    ]

    width, height = 495, 150
    col_w = width / 3

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        f"<rect x='0.5' y='0.5' width='{width - 1}' height='{height - 1}' rx='8' fill='{bg}' stroke='{border}'/>",
        f"<text x='{width / 2}' y='28' text-anchor='middle' font-family='Segoe UI, Ubuntu, sans-serif' font-size='13' fill='{muted}'>@{login} · GitHub streak</text>",
        f"<line x1='{col_w:.0f}' y1='40' x2='{col_w:.0f}' y2='{height - 16}' stroke='{border}' stroke-width='1'/>",
        f"<line x1='{col_w * 2:.0f}' y1='40' x2='{col_w * 2:.0f}' y2='{height - 16}' stroke='{border}' stroke-width='1'/>",
    ]

    for i, (label, value, sub) in enumerate(columns):
        cx = col_w * i + col_w / 2
        parts.append(
            f"<text x='{cx:.0f}' y='82' text-anchor='middle' font-family='Segoe UI, Ubuntu, sans-serif' "
            f"font-size='30' font-weight='700' fill='{accent}'>{value}</text>"
        )
        parts.append(
            f"<text x='{cx:.0f}' y='106' text-anchor='middle' font-family='Segoe UI, Ubuntu, sans-serif' "
            f"font-size='13' fill='{fg}'>{label}</text>"
        )
        parts.append(
            f"<text x='{cx:.0f}' y='126' text-anchor='middle' font-family='Segoe UI, Ubuntu, sans-serif' "
            f"font-size='11' fill='{muted}'>{sub}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)


def main():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GITHUB_LOGIN", "KostinP")
    if not token:
        print("GITHUB_TOKEN env var is required", file=sys.stderr)
        sys.exit(1)

    days, created_at = fetch_all_days(token, login)
    stats = compute_stats(days)
    svg = render_svg(stats, login, created_at)

    out_path = os.path.abspath(OUT_PATH)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(svg)

    print(f"total={stats['total']} current={stats['current_len']} best={stats['best_len']}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
