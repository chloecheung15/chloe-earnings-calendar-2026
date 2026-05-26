#!/usr/bin/env python3
"""Generate an Apple Calendar compatible earnings subscription for Chloe's watchlist.

Source for automatically discovered dates: Finnhub Earnings Calendar API.
Dates fetched from Finnhub are labelled as data-source previews (not official IR confirmation).
The script fails safely: if every API call fails, it does not overwrite the existing .ics file.
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
MANUAL_PATH = ROOT / "data" / "manual_confirmed_events.json"
CACHE_PATH = ROOT / "data" / "api_cache.json"
OUTPUT_PATH = ROOT / "earnings_calendar.ics"
CALENDAR_YEAR = int(os.getenv("CALENDAR_YEAR", "2026"))
PAST_LOOKBACK_DAYS = int(os.getenv("PAST_LOOKBACK_DAYS", "90"))
API_URL = "https://finnhub.io/api/v1/calendar/earnings"
FIXED_DTSTAMP = "20260526T000000Z"

HOUR_LABELS = {
    "bmo": "盘前 / Before Market Open",
    "amc": "盘后 / After Market Close",
    "dmh": "盘中 / During Market Hours",
    "": "时间待公布",
    None: "时间待公布",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_symbol_events(api_key: str, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"from": start, "to": end, "symbol": symbol, "international": "false"})
    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"X-Finnhub-Token": api_key, "Accept": "application/json", "User-Agent": "ChloeEarningsCalendar/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{symbol}: Finnhub request failed: {exc}") from exc
    entries = payload.get("earningsCalendar", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        raise RuntimeError(f"{symbol}: Unexpected Finnhub response format")
    return [item for item in entries if str(item.get("symbol", "")).upper() == symbol]


def normalize_api_event(item: dict[str, Any], meta: dict[str, str]) -> dict[str, Any] | None:
    day = str(item.get("date", ""))
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return None
    if parsed.year != CALENDAR_YEAR:
        return None
    return {
        "symbol": meta["symbol"],
        "company": meta["company"],
        "priority": meta["priority"],
        "theme": meta["theme"],
        "date": day,
        "hour": item.get("hour", ""),
        "fiscalQuarter": item.get("quarter"),
        "fiscalYear": item.get("year"),
        "epsEstimate": item.get("epsEstimate"),
        "revenueEstimate": item.get("revenueEstimate"),
        "source_type": "finnhub_preview",
    }


def event_identity(event: dict[str, Any]) -> str:
    symbol = event["symbol"]
    fy, fq = event.get("fiscalYear"), event.get("fiscalQuarter")
    if fy is not None and fq is not None:
        return f"{symbol}-FY{fy}-Q{fq}"
    return f"{symbol}-{event['date']}"


def merge_api_with_cache(fetched_by_symbol: dict[str, list[dict[str, Any]]], cache: list[dict[str, Any]], query_start: date) -> list[dict[str, Any]]:
    old_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for event in cache:
        old_by_symbol.setdefault(event["symbol"], []).append(event)
    merged: list[dict[str, Any]] = []
    for symbol, fetched in fetched_by_symbol.items():
        if fetched:
            merged.extend(fetched)
        else:
            # If no new date is supplied yet, keep non-expired cached events so a
            # previously announced upcoming event does not vanish from the phone.
            merged.extend(e for e in old_by_symbol.get(symbol, []) if date.fromisoformat(e["date"]) >= query_start)
    dedup = {event_identity(e): e for e in merged}
    return sorted(dedup.values(), key=lambda e: (e["date"], e["symbol"]))


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


def fmt_estimate(value: Any, kind: str) -> str:
    if value in (None, ""):
        return "未提供"
    if kind == "revenue":
        try:
            number = float(value)
            if abs(number) >= 1_000_000_000:
                return f"${number / 1_000_000_000:.2f}B"
            if abs(number) >= 1_000_000:
                return f"${number / 1_000_000:.2f}M"
        except (TypeError, ValueError):
            pass
    return str(value)


def render_event(event: dict[str, Any]) -> list[str]:
    day = date.fromisoformat(event["date"])
    next_day = day + timedelta(days=1)
    official = event.get("source_type") == "manual_confirmed"
    marker = "✅" if official else "⏳"
    status = "官网确认" if official else "数据源预告｜请在交易前以公司 IR 为准"
    timing = event.get("timing") if official else HOUR_LABELS.get(event.get("hour"), "时间待公布")
    summary = f"{event['priority']} {marker} 财报｜{event['symbol']} {event['company']}｜{event['theme']}"
    description = [
        f"状态：{status}",
        f"股票：{event['symbol']}｜{event['company']}",
        f"时间：{timing}",
        f"关注重点：{event['theme']}",
    ]
    if not official:
        description.extend([
            f"Fiscal period：FY{event.get('fiscalYear', '?')} Q{event.get('fiscalQuarter', '?')}",
            f"EPS estimate：{fmt_estimate(event.get('epsEstimate'), 'eps')}",
            f"Revenue estimate：{fmt_estimate(event.get('revenueEstimate'), 'revenue')}",
            "数据源：Finnhub Earnings Calendar API（日期可能改期）",
        ])
    else:
        description.append(f"官方来源：{event.get('url', '')}")
    uid = f"{event_identity(event)}@chloe-earnings-calendar"
    return [
        "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{FIXED_DTSTAMP}",
        f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{next_day.strftime('%Y%m%d')}",
        f"SUMMARY:{esc(summary)}", f"DESCRIPTION:{esc(chr(10).join(description))}",
        f"CATEGORIES:{esc('美股财报')},{event['symbol']}", "STATUS:CONFIRMED", "TRANSP:TRANSPARENT",
        "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", f"DESCRIPTION:{esc('明天财报：' + event['symbol'])}", "END:VALARM", "END:VEVENT",
    ]


def write_ics(events: list[dict[str, Any]]) -> None:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Chloe Earnings Radar Auto//ChatGPT//ZH",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:2026 美股财报雷达｜26只核心观察股｜自动更新",
        "X-WR-CALDESC:自动抓取 Finnhub 财报日历；⏳ 为数据源预告，交易前请核对公司 IR。",
        "X-APPLE-CALENDAR-COLOR:#E45756", "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
    ]
    for event in sorted(events, key=lambda e: (e["date"], e["symbol"])):
        lines.extend(render_event(event))
    lines.append("END:VCALENDAR")
    OUTPUT_PATH.write_text("\r\n".join(fold_line(line) for line in lines) + "\r\n", encoding="utf-8")


def main() -> int:
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        print("FINNHUB_API_KEY is missing. The existing calendar was not changed.", file=sys.stderr)
        return 2
    tickers: list[dict[str, str]] = load_json(TICKERS_PATH)
    manual: list[dict[str, Any]] = load_json(MANUAL_PATH)
    cache: list[dict[str, Any]] = load_json(CACHE_PATH)
    today = datetime.now(timezone.utc).date()
    year_start, year_end = date(CALENDAR_YEAR, 1, 1), date(CALENDAR_YEAR, 12, 31)
    query_start = max(year_start, today - timedelta(days=PAST_LOOKBACK_DAYS))
    if query_start > year_end:
        print(f"Calendar year {CALENDAR_YEAR} has ended; leaving existing file unchanged.")
        return 0
    fetched_by_symbol: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for meta in tickers:
        symbol = meta["symbol"]
        try:
            raw = fetch_symbol_events(api_key, symbol, query_start.isoformat(), year_end.isoformat())
            fetched_by_symbol[symbol] = [evt for item in raw if (evt := normalize_api_event(item, meta))]
        except RuntimeError as exc:
            errors.append(str(exc))
            # Failed symbol retains cached, non-expired events.
            fetched_by_symbol[symbol] = [e for e in cache if e.get("symbol") == symbol and date.fromisoformat(e["date"]) >= query_start]
    if len(errors) == len(tickers):
        print("All Finnhub requests failed. Existing .ics was not overwritten.", file=sys.stderr)
        for message in errors:
            print(message, file=sys.stderr)
        return 1
    api_events = merge_api_with_cache(fetched_by_symbol, cache, query_start)
    manual_keys = {event_identity(e) for e in manual}
    combined = [e for e in api_events if event_identity(e) not in manual_keys] + manual
    write_json(CACHE_PATH, api_events)
    write_ics(combined)
    print(f"Generated {OUTPUT_PATH.name}: {len(combined)} events across {len(tickers)} tracked symbols.")
    if errors:
        print(f"Warning: {len(errors)} symbol requests failed; cached upcoming events were preserved where available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
