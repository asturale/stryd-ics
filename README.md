# stryd-ics

Turns your planned [Stryd](https://www.stryd.com/) workouts into a subscribable ICS calendar feed. Stryd has no public/documented calendar export, so this logs in with your Stryd credentials (same as the app) and reads the same calendar endpoint the web app itself uses.

Only **planned, not-yet-completed** workouts (today or in the future) are included — once you've logged a run in Stryd, it drops off the feed.

Runs as a single container: it refreshes the feed in the background on a timer and serves the current cached copy over HTTP. No cron, no separate web server.

## Quick start

```bash
docker run -d \
  -e STRYD_EMAIL=you@example.com \
  -e STRYD_PASSWORD=your-password \
  -e ICS_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(20))") \
  -p 8080:8080 \
  ghcr.io/asturale/stryd-ics:latest
```

Or with Docker Compose — copy `.env.example` to `.env`, fill it in, then:

```bash
docker compose up -d
```

Subscribe to `http://<host>:8080/<ICS_TOKEN>.ics` in Google Calendar, Fastmail, Apple Calendar, Outlook, etc. Put a reverse proxy (Caddy, nginx, a Cloudflare Tunnel) in front for HTTPS if exposing it outside your own network — most calendar apps expect (or strongly prefer) HTTPS for subscribed feeds.

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `STRYD_EMAIL` | yes | — | Your Stryd account email |
| `STRYD_PASSWORD` | yes | — | Your Stryd account password |
| `ICS_TOKEN` | no | *(none)* | Secret path segment: feed is served at `/<ICS_TOKEN>.ics`. If unset, served at the guessable `/calendar.ics` — set this if the container is reachable from the internet |
| `TZ_NAME` | no | `Europe/Amsterdam` | IANA timezone used to resolve workout dates |
| `CALNAME` | no | `Stryd workouts` | Calendar display name (`X-WR-CALNAME`) |
| `REFRESH_SECONDS` | no | `21600` (6h) | How often to re-fetch from Stryd |
| `LOOKAHEAD_DAYS` | no | `150` | How far ahead to request planned workouts |
| `REMINDER_HOUR` | no | *(none)* | Add a reminder (`VALARM`) at this local hour (0-23) on the workout day. Many calendar clients ignore embedded reminders on subscribed/read-only feeds and use their own default instead — try it, but don't rely on it |
| `PORT` | no | `8080` | HTTP listen port |

## Security notes

- Your Stryd credentials are only ever sent to `stryd.com`/`api.stryd.com`, and only from inside the container.
- Treat the feed URL like a password if you set `ICS_TOKEN` — anyone with the URL can read your planned workouts. There's no further auth; put it behind a reverse proxy with IP/ASN restrictions if you want to lock it down further (e.g. to your calendar provider's network only).
- This uses Stryd's undocumented web-app API (the same one [stryd.com](https://www.stryd.com) itself uses when logged in via a browser) — not an official integration. It may break if Stryd changes their app.

## How it works

Stryd's calendar data lives at `api.stryd.com` (not the same host as the login endpoint), and returns a `workouts` array. A workout with no `activity_id` hasn't been run yet — those (today or later) become all-day `VEVENT`s in the output, RFC5545 line-folded, with an optional `VALARM`.

## License

MIT — see [LICENSE](LICENSE).
