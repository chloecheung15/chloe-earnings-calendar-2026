#!/usr/bin/env python3
"""Generate a clean Apple Calendar earnings feed for Chloe using Finnhub.

Event title format:
    ⏳ 财报｜NVDA｜AI GPU / Data Center

All automatically fetched events use ⏳ because Finnhub does not expose a
company-IR confirmation status flag. This calendar preserves a rolling view
of 2026: historical 2026 events plus available upcoming dates.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TICKERS_PATH = ROOT / "data" / "tickers.json"
CACHE_PATH = ROOT / "data" / "api_cache.json"
OUTPUT_PATH = ROOT / "earnings_calendar.ics"

API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
CALENDAR_YEAR = int(os.getenv("CALENDAR_YEAR", "2026"))
FORECAST_DAYS_AHEAD = int(os.getenv("FORECAST_DAYS_AHEAD", "90"))
API_BASE = "https://finnhub.io/api/v1/calendar/earnings"

HOUR_LABELS = {
    "bmo": "盘前 / Before Market Open",
    "amc": "盘后 / After Market Close",
    "dmh": "盘中 / During Market Hours",
    "": "时间待公布",
    None: "时间待公布",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def windows(start: date, end: date) -> list[tuple[date, date]]:
    result = []
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + timedelta(days=30))
        result.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return result


def fetch_window(start: date, end: date) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({
        "from": start.isoformat(),
        "to": end.isoformat(),
        "token": API_KEY,
    })
    url = f"{API_BASE}?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ChloeEarningsCalendar/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Finnhub request failed for {start} to {end}: {exc}") from exc
    items = payload.get("earningsCalendar", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        raise RuntimeError(f"Unexpected Finnhub response for {start} to {end}.")
    return items


def normalize(raw: dict[str, Any], themes: dict[str, str]) -> dict[str, Any] | None:
    symbol = str(raw.get("symbol", "")).upper().strip()
    if symbol not in themes:
        return None
    day_text = str(raw.get("date", "")).strip()
    try:
        date.fromisoformat(day_text)
    except ValueError:
        return None
    return {
        "symbol": symbol,
        "date": day_text,
        "theme": themes[symbol],
        "hour": raw.get("hour"),
        "quarter": raw.get("quarter"),
        "year": raw.get("year"),
        "epsEstimate": raw.get("epsEstimate"),
        "revenueEstimate": raw.get("revenueEstimate"),
        "source": "Finnhub Earnings Calendar",
    }


def esc(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold_line(line: str) -> str:
    chunks = []
    remainder = line
    first = True
    while remainder:
        byte_limit = 75 if first else 74
        piece = ""
        for ch in remainder:
            if len((piece + ch).encode("utf-8")) > byte_limit:
                break
            piece += ch
        if not piece:
            piece = remainder[0]
        chunks.append(("" if first else " ") + piece)
        remainder = remainder[len(piece):]
        first = False
    return "\r\n".join(chunks)


def detail_lines(event: dict[str, Any]) -> list[str]:
    timing = HOUR_LABELS.get(event.get("hour"), "时间待公布")
    quarter = event.get("quarter")
    year = event.get("year")
    period = f"FY{year} Q{quarter}" if year and quarter else "财报季度待补充"
    return [
        "状态：⏳ 数据源财报日程，持仓跨财报前请核对公司 IR 官网",
        f"股票：{event['symbol']}",
        f"期间：{period}",
        f"时间：{timing}",
        f"关注重点：{event['theme']}",
        "数据来源：Finnhub Earnings Calendar",
    ]


def render_ics(events: list[dict[str, Any]]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chloe Earnings Radar Finnhub//ChatGPT//ZH",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:2026 美股财报雷达｜26只观察股",
        "X-WR-CALDESC:2026全年滚动保留；⏳=自动抓取财报日程，下单前请核对公司IR官网。",
        "X-APPLE-CALENDAR-COLOR:#E45756",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for event in sorted(events, key=lambda e: (e["date"], e["symbol"])):
        d = date.fromisoformat(event["date"])
        summary = f"⏳ 财报｜{event['symbol']}｜{event['theme']}"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event['symbol']}-{event['date']}-earnings@chloe-calendar",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(chr(10).join(detail_lines(event)))}",
            f"CATEGORIES:{esc('美股财报')},{event['symbol']}",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "TRIGGER:-P1D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{esc('明天财报：' + event['symbol'])}",
            "END:VALARM",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"


def main() -> int:
    if not API_KEY:
        print("FINNHUB_API_KEY is missing; existing .ics was not overwritten.", file=sys.stderr)
        return 2

    tickers = load_json(TICKERS_PATH)
    themes = {item["symbol"].upper(): item["theme"] for item in tickers}
    today = datetime.now(timezone.utc).date()
    start = date(CALENDAR_YEAR, 1, 1)
    year_end = date(CALENDAR_YEAR, 12, 31)
    end = year_end if today > year_end else min(year_end, today + timedelta(days=FORECAST_DAYS_AHEAD))

    try:
        raw_events: list[dict[str, Any]] = []
        for window_start, window_end in windows(start, end):
            raw_events.extend(fetch_window(window_start, window_end))
    except RuntimeError as exc:
        print(f"{exc}\nExisting .ics was not overwritten.", file=sys.stderr)
        return 1

    events = []
    for raw in raw_events:
        item = normalize(raw, themes)
        if item:
            events.append(item)
    deduped = {(e["symbol"], e["date"]): e for e in events}
    chosen = list(deduped.values())

    if not chosen:
        print("Finnhub returned no matching watchlist events; existing .ics was not overwritten.", file=sys.stderr)
        return 1

    write_json(CACHE_PATH, chosen)
    OUTPUT_PATH.write_text(render_ics(chosen), encoding="utf-8")
    print(f"Generated {OUTPUT_PATH.name}: {len(chosen)} events for {CALENDAR_YEAR} through {end.isoformat()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
