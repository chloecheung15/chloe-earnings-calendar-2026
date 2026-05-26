#!/usr/bin/env python3
"""Generate Chloe's Apple Calendar earnings feed from EarningsCalendar.net.

Display:
  ⏳ 财报｜NVDA｜AI GPU / Data Center  = projected date
  ✅ 财报｜NVDA｜AI GPU / Data Center  = confirmed via company press release dataset

The program queries confirmed and projected data separately so the status emoji
can upgrade automatically. If any required API request fails, it leaves the
existing .ics untouched to avoid silently deleting calendar events.
"""
from __future__ import annotations

import json
import os
import sys
import time
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

API_KEY = os.getenv("EARNINGSCALENDAR_API_KEY", "").strip()
API_BASE = os.getenv("EARNINGSCALENDAR_API_BASE", "https://api.earningscalendar.net").rstrip("/")
CALENDAR_YEAR = int(os.getenv("CALENDAR_YEAR", "2026"))
FORECAST_DAYS_AHEAD = int(os.getenv("FORECAST_DAYS_AHEAD", "90"))
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "1.1"))

WHEN_LABELS = {
    "premarket": "盘前 / Before Market Open",
    "pre-market": "盘前 / Before Market Open",
    "postmarket": "盘后 / After Market Close",
    "afterhours": "盘后 / After Market Close",
    "after-hours": "盘后 / After Market Close",
    "duringmarket": "盘中 / During Market Hours",
    "null": "时间待公布",
    "": "时间待公布",
    None: "时间待公布",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def date_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Create inclusive windows no longer than 31 calendar days."""
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + timedelta(days=30))
        windows.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return windows


def request_events(endpoint: str, start: date, end: date, symbols: list[str]) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "tickers": ",".join(symbols),
        "api_key": API_KEY,
    })
    url = f"{API_BASE}/{endpoint}?{params}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "ChloeEarningsCalendar/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Request failed for {endpoint} {start} to {end}: {exc}") from exc

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "earnings"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise RuntimeError(f"Unexpected response format for {endpoint} {start} to {end}")


def normalize(raw: dict[str, Any], theme_by_symbol: dict[str, str], confirmed: bool) -> dict[str, Any] | None:
    symbol = str(raw.get("ticker", "")).upper()
    if symbol not in theme_by_symbol:
        return None
    try:
        event_date = date.fromisoformat(str(raw.get("date", "")))
    except ValueError:
        return None
    event = {
        "symbol": symbol,
        "theme": theme_by_symbol[symbol],
        "date": event_date.isoformat(),
        "when": raw.get("when"),
        "source_type": "confirmed" if confirmed else "projected",
    }
    if confirmed:
        event["confirmation_url"] = raw.get("url", "")
        event["confirmation_title"] = raw.get("title", "")
        event["confirmation_published_at"] = raw.get("pub_date", "")
    else:
        event["weight"] = raw.get("weight")
        event["updated_at"] = raw.get("updated_at", "")
    return event


def select_best_events(projected: list[dict[str, Any]], confirmed: list[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
    """If a symbol has a confirmed event in the window, show it instead of projections."""
    confirmed_by_symbol: dict[str, list[dict[str, Any]]] = {}
    projected_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for event in confirmed:
        confirmed_by_symbol.setdefault(event["symbol"], []).append(event)
    for event in projected:
        projected_by_symbol.setdefault(event["symbol"], []).append(event)

    chosen: list[dict[str, Any]] = []
    for symbol in symbols:
        source = confirmed_by_symbol.get(symbol) or projected_by_symbol.get(symbol, [])
        dedup = {(event["symbol"], event["date"]): event for event in source}
        chosen.extend(dedup.values())
    return sorted(chosen, key=lambda event: (event["date"], event["symbol"]))


def esc(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold_line(line: str) -> str:
    segments: list[str] = []
    remaining = line
    first = True
    while remaining:
        max_bytes = 75 if first else 74
        part = ""
        for char in remaining:
            if len((part + char).encode("utf-8")) > max_bytes:
                break
            part += char
        if not part:
            part = remaining[0]
        segments.append(("" if first else " ") + part)
        remaining = remaining[len(part):]
        first = False
    return "\r\n".join(segments)


def render_event(event: dict[str, Any]) -> list[str]:
    day = date.fromisoformat(event["date"])
    marker = "✅" if event["source_type"] == "confirmed" else "⏳"
    summary = f"{marker} 财报｜{event['symbol']}｜{event['theme']}"
    timing = WHEN_LABELS.get(str(event.get("when", "")).lower(), "时间待公布")

    if event["source_type"] == "confirmed":
        detail = [
            "状态：✅ 公司公告确认日期",
            f"股票：{event['symbol']}",
            f"时间：{timing}",
            f"关注重点：{event['theme']}",
            f"确认公告：{event.get('confirmation_title', '')}",
            f"公告发布时间：{event.get('confirmation_published_at', '')}",
            f"确认来源：{event.get('confirmation_url', '')}",
        ]
    else:
        detail = [
            "状态：⏳ 预计日期，尚未在确认数据集中匹配到公司公告",
            f"股票：{event['symbol']}",
            f"时间：{timing}",
            f"关注重点：{event['theme']}",
            "提醒：买入期权或跨财报持仓前，请再次核对公司 IR 官网。",
            "数据源：EarningsCalendar.net Projected Earnings",
        ]

    uid = f"{event['symbol']}-{event['date']}-earnings@chloe-calendar"
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{esc(summary)}",
        f"DESCRIPTION:{esc(chr(10).join(detail))}",
        f"CATEGORIES:{esc('美股财报')},{event['symbol']}",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM",
        "TRIGGER:-P1D",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{esc('明天财报：' + event['symbol'])}",
        "END:VALARM",
        "END:VEVENT",
    ]


def write_ics(events: list[dict[str, Any]]) -> None:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chloe Earnings Radar Auto Confirm//ChatGPT//ZH",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:2026 美股财报雷达｜26只观察股｜全年滚动",
        "X-WR-CALDESC:2026全年滚动保留；⏳=预计日期；✅=公司公告确认日期。",
        "X-APPLE-CALENDAR-COLOR:#E45756",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    for event in events:
        lines.extend(render_event(event))
    lines.append("END:VCALENDAR")
    OUTPUT_PATH.write_text("\r\n".join(fold_line(line) for line in lines) + "\r\n", encoding="utf-8")


def main() -> int:
    if not API_KEY:
        print("EARNINGSCALENDAR_API_KEY is missing; existing .ics was not changed.", file=sys.stderr)
        return 2

    tickers: list[dict[str, str]] = load_json(TICKERS_PATH)
    symbols = [entry["symbol"].upper() for entry in tickers]
    themes = {entry["symbol"].upper(): entry["theme"] for entry in tickers}
    today = datetime.now(timezone.utc).date()
    year_start = date(CALENDAR_YEAR, 1, 1)
    year_end = date(CALENDAR_YEAR, 12, 31)

    # Full-year rolling archive:
    # - preserve/query 2026 historical events from January 1 onward;
    # - add future events as they enter the reliable forward-looking window.
    start = year_start
    if today <= year_end:
        end = min(year_end, today + timedelta(days=max(1, FORECAST_DAYS_AHEAD) - 1))
    else:
        end = year_end

    projected_raw: list[dict[str, Any]] = []
    confirmed_raw: list[dict[str, Any]] = []

    try:
        windows = date_windows(start, end)
        for index, (window_start, window_end) in enumerate(windows):
            projected_raw.extend(request_events("earnings", window_start, window_end, symbols))
            time.sleep(REQUEST_DELAY_SECONDS)
            confirmed_raw.extend(request_events("confirmed_earnings", window_start, window_end, symbols))
            if index < len(windows) - 1:
                time.sleep(REQUEST_DELAY_SECONDS)
    except RuntimeError as exc:
        print(f"{exc}\nExisting .ics was not overwritten.", file=sys.stderr)
        return 1

    projected = [event for item in projected_raw if (event := normalize(item, themes, confirmed=False))]
    confirmed = [event for item in confirmed_raw if (event := normalize(item, themes, confirmed=True))]
    chosen = select_best_events(projected, confirmed, symbols)

    write_json(CACHE_PATH, chosen)
    write_ics(chosen)
    confirmed_count = sum(1 for event in chosen if event["source_type"] == "confirmed")
    print(f"Generated {OUTPUT_PATH.name}: {len(chosen)} events for {CALENDAR_YEAR} through {end.isoformat()}; {confirmed_count} confirmed; {len(chosen) - confirmed_count} projected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
