#!/usr/bin/env python3
"""Generate Chloe's Apple Calendar earnings feed using Finnhub.

Calendar event titles:
    📊 NVDA｜盘后财报
    📊 LMT｜盘前财报
    📊 RKLB｜财报时间待定

Finnhub supplies an earnings-calendar schedule and a before/after/during-market
indicator where available. It does not supply a reliable company-IR-confirmed
status field, so all automatic events retain the ⏳ marker.
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

TITLE_TIME_LABELS = {
    "bmo": "盘前财报",
    "amc": "盘后财报",
    "dmh": "盘中财报",
    "": "财报时间待定",
    None: "财报时间待定",
}
DETAIL_TIME_LABELS = {
    "bmo": "盘前 / Before Market Open",
    "amc": "盘后 / After Market Close",
    "dmh": "盘中 / During Market Hours",
    "": "时间待定",
    None: "时间待定",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
    request = urllib.request.Request(
        f"{API_BASE}?{query}",
        headers={"Accept": "application/json", "User-Agent": "ChloeEarningsCalendar/Final"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
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
        for char in remainder:
            if len((piece + char).encode("utf-8")) > byte_limit:
                break
            piece += char
        if not piece:
            piece = remainder[0]
        chunks.append(("" if first else " ") + piece)
        remainder = remainder[len(piece):]
        first = False
    return "\r\n".join(chunks)


def detail_lines(event: dict[str, Any]) -> list[str]:
    timing = DETAIL_TIME_LABELS.get(event.get("hour"), "时间待定")
    quarter = event.get("quarter")
    year = event.get("year")
    period = f"FY{year} Q{quarter}" if year and quarter else "财报季度待补充"
    return [
        "状态：⏳ 自动抓取财报日程，跨财报持仓前请核对公司 IR 官网",
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
        "PRODID:-//Chloe Earnings Radar Finnhub Final//ChatGPT//ZH",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:2026 美股财报雷达｜26只观察股",
        "X-WR-CALDESC:2026全年滚动保留；📊=财报事件；跨财报持仓前请核对公司IR官网。",
        "X-APPLE-CALENDAR-COLOR:#E45756",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for event in sorted(events, key=lambda e: (e["date"], e["symbol"])):
        event_date = date.fromisoformat(event["date"])
        timing = TITLE_TIME_LABELS.get(event.get("hour"), "财报时间待定")
        summary = f"📊 {event['symbol']}｜{timing}"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event['symbol']}-{event['date']}-earnings@chloe-calendar",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{event_date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(event_date + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(chr(10).join(detail_lines(event)))}",
            f"CATEGORIES:{esc('美股财报')},{event['symbol']}",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "TRIGGER:-P1D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{esc('明天：' + event['symbol'] + '｜' + timing)}",
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
    year_start = date(CALENDAR_YEAR, 1, 1)
    year_end = date(CALENDAR_YEAR, 12, 31)
    end = year_end if today > year_end else min(year_end, today + timedelta(days=FORECAST_DAYS_AHEAD))

    try:
        raw_events: list[dict[str, Any]] = []
        for window_start, window_end in windows(year_start, end):
            raw_events.extend(fetch_window(window_start, window_end))
    except RuntimeError as exc:
        print(f"{exc}\nExisting .ics was not overwritten.", file=sys.stderr)
        return 1

    matched_events = []
    for raw in raw_events:
        event = normalize(raw, themes)
        if event:
            matched_events.append(event)
    deduped = {(event["symbol"], event["date"]): event for event in matched_events}
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
