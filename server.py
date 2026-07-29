#!/usr/bin/env python3
"""stryd-ics: exposes your planned Stryd workouts as a subscribable ICS feed.

Stryd has no public/documented calendar export, so this logs in with your
Stryd credentials (same as the app) and reads the same calendar endpoint the
web app uses. Only PLANNED, not-yet-completed workouts (no activity_id) that
are today or in the future are included.

Runs as a single long-lived process: refreshes the feed on a timer in the
background and serves the current cached copy over HTTP.

Endpoints:
  GET /<ICS_TOKEN>.ics   -> the calendar feed (path secret if ICS_TOKEN is set)
  GET /healthz            -> liveness check
"""
import datetime
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

STRYD_EMAIL = os.environ["STRYD_EMAIL"]
STRYD_PASSWORD = os.environ["STRYD_PASSWORD"]
ICS_TOKEN = os.environ.get("ICS_TOKEN", "").strip()
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Amsterdam"))
CALNAME = os.environ.get("CALNAME", "Stryd workouts")
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "21600"))  # 6h, matches Stryd plan-update cadence
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "150"))
PORT = int(os.environ.get("PORT", "8080"))
# Optional: add a VALARM reminder at this local hour (0-23) on the workout day.
# Leave unset to omit reminders (many calendar clients ignore embedded VALARMs
# on subscribed/read-only feeds anyway and use their own default instead).
REMINDER_HOUR = os.environ.get("REMINDER_HOUR", "").strip()

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

_cache = {"data": None, "ts": 0}
_lock = threading.Lock()


def call(url, data=None, hdr=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(hdr or {})
    b = None
    m = "GET"
    if data is not None:
        b = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
        m = "POST"
    req = urllib.request.Request(url, data=b, headers=h, method=m)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def esc(s):
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line):
    """RFC5545 line folding: max 75 octets per line, continuation lines
    prefixed with a single space, never splitting inside a UTF-8 sequence."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    chunks = []
    limit = 75
    while b:
        cut = min(limit, len(b))
        while cut > 0 and cut < len(b) and (b[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(b[:cut])
        b = b[cut:]
        limit = 74  # room for the leading continuation space
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def build_ics():
    auth = call("https://www.stryd.com/b/email/signin",
                {"email": STRYD_EMAIL, "password": STRYD_PASSWORD})
    tok, uid = auth["token"], auth["id"]
    now = int(time.time())
    url = (f"https://api.stryd.com/b/api/v1/users/{uid}/calendar"
           f"?from={now - 3 * 86400}&to={now + LOOKAHEAD_DAYS * 86400}&include_deleted=false")
    cal = call(url, hdr={"Authorization": "Bearer: " + tok})
    today = datetime.datetime.now(TZ).date()

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//stryd-ics//NL",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{CALNAME}",
              f"X-WR-TIMEZONE:{TZ.key}", "REFRESH-INTERVAL;VALUE=DURATION:PT6H"]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    count = 0
    for w in cal.get("workouts", []):
        if w.get("activity_id"):  # already completed -> skip
            continue
        try:
            d_utc = datetime.datetime.fromisoformat(w["date"].replace("Z", "+00:00"))
        except Exception:
            continue
        d_local = d_utc.astimezone(TZ).date()
        if d_local < today:  # missed plan -> skip
            continue

        wk = w.get("workout") or {}
        title = wk.get("title") or wk.get("name") or "Workout"
        km = (w.get("distance") or 0) / 1000.0
        mins = round((w.get("duration") or 0) / 60)
        stress = w.get("stress")

        summary = f"\U0001F3C3 {title}"
        if km:
            summary += f" — {km:.1f} km"
        if mins:
            summary += f" / {mins} min"

        desc_parts = []
        if wk.get("notification_text"):
            desc_parts.append(wk["notification_text"])
        if wk.get("desc"):
            desc_parts.append(wk["desc"])
        meta = []
        if km:
            meta.append(f"Distance: {km:.1f} km")
        if mins:
            meta.append(f"Duration: ~{mins} min")
        if wk.get("type"):
            meta.append(f"Type: {wk['type']}")
        if stress:
            meta.append(f"Stress: {stress:.0f}")
        if meta:
            desc_parts.append(" | ".join(meta))
        desc_parts.append("Source: Stryd (planned)")

        ds = d_local.strftime("%Y%m%d")
        de = (d_local + datetime.timedelta(days=1)).strftime("%Y%m%d")
        full_desc = esc("\n\n".join(p for p in desc_parts if p))

        event = ["BEGIN:VEVENT",
                 f"UID:stryd-{w.get('id')}@stryd-ics",
                 f"DTSTAMP:{stamp}",
                 f"DTSTART;VALUE=DATE:{ds}",
                 f"DTEND;VALUE=DATE:{de}",
                 f"SUMMARY:{esc(summary)}",
                 "DESCRIPTION:" + full_desc,
                 "TRANSP:TRANSPARENT"]

        if REMINDER_HOUR != "":
            alarm_local = datetime.datetime.combine(
                d_local, datetime.time(int(REMINDER_HOUR), 0), tzinfo=TZ)
            alarm_utc = alarm_local.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            event += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Workout today",
                      f"TRIGGER;VALUE=DATE-TIME:{alarm_utc}", "END:VALARM"]

        event.append("END:VEVENT")
        lines += event
        count += 1

    lines.append("END:VCALENDAR")
    out = ("\r\n".join(fold(l) for l in lines) + "\r\n").encode("utf-8")
    sys.stderr.write(f"[stryd-ics] {count} planned workout(s)\n")
    return out


def get_ics_cached():
    with _lock:
        now = time.time()
        if _cache["data"] is not None and (now - _cache["ts"]) < REFRESH_SECONDS:
            return _cache["data"]
    data = build_ics()
    with _lock:
        _cache["data"] = data
        _cache["ts"] = time.time()
    return data


def refresh_loop():
    while True:
        try:
            get_ics_cached()
        except Exception as e:
            sys.stderr.write(f"[stryd-ics] refresh failed: {e}\n")
        time.sleep(REFRESH_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, b"ok")
            return

        expected_path = f"/{ICS_TOKEN}.ics" if ICS_TOKEN else "/calendar.ics"
        if self.path == expected_path:
            try:
                data = get_ics_cached()
            except Exception as e:
                self._send(502, f"upstream fetch failed: {e}")
                return
            self._send(200, data, content_type="text/calendar; charset=utf-8")
            return

        self._send(404, "not found")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=refresh_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
