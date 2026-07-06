#!/usr/bin/env python3
"""
Builds a .ics calendar feed from Vidiots' "Coming Soon" page
(https://vidiotsfoundation.org/coming-soon/), so it can be subscribed to
in Google Calendar.

WHY IT WORKS THIS WAY
----------------------
Vidiots' site runs on the Filmbot ticketing platform, which doesn't publish
its own calendar/iCal feed. The "Coming Soon" page lists each film with a
set of date tabs and a flat list of showtime links -- but for films with
several showtimes across several days, the page doesn't cleanly say which
time belongs to which date in a way that's safe to infer.

Each individual ticket page (https://vidiotsfoundation.org/purchase/<id>/)
DOES disclose the exact date, time, and auditorium for that one showing
(it has to, since you're about to buy a ticket for it). So this script:

  1. Reads /coming-soon/ for each film's title, page URL, and showtime
     ("purchase") links.
  2. Visits each purchase link to get the authoritative date/time/location.
  3. Writes it all out as a standard .ics file.

A NOTE ON RELIABILITY
----------------------
This was written by inspecting a text-rendered view of the site's pages,
not the raw HTML source (I didn't have a way to fetch raw HTML for this
particular domain from where I built it). The parsing below uses heuristics
(regex on href patterns and label text, like "Run Time:" or "Date & Time")
rather than hard-coded CSS class names, which should make it fairly
resilient -- but it hasn't been run against the live site yet. Run with
--debug first (see README) before wiring it into anything automated, and
expect to tweak a regex or two based on what you see.

Only showtimes with an online purchase link can be resolved this way.
"Limited Walk-Up" showtimes (text only, no link) are skipped, since there's
no page to confirm their exact date/time against.
"""

import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://vidiotsfoundation.org"
COMING_SOON_URL = f"{BASE_URL}/coming-soon/"
LA_TZ = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PersonalVidiotsCalendarBot/1.0; "
    "for personal calendar sync, low request volume)"
}
REQUEST_DELAY_SECONDS = 0.6  # be polite -- this hits their real server
DEFAULT_RUNTIME_MIN = 120  # fallback if we can't find a runtime for a film


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def get_movie_blocks(html):
    """
    Returns a list of dicts, one per film on the Coming Soon page:
      { title, movie_url, purchase_ids: [...], runtime_min, director }

    Strategy: find each <h2><a href="/movies/...">Title</a></h2>, then climb
    up through ancestor elements until we find one that looks like a
    self-contained card (contains "Run Time" and the "Please select a
    showtime" boilerplate, but not a second film's title). That container's
    text and links are then used to pull out runtime, director, and all
    /purchase/<id>/ links for that film.
    """
    soup = BeautifulSoup(html, "html.parser")
    h2_tags = [h2 for h2 in soup.find_all("h2") if h2.find("a", href=re.compile(r"/movies/"))]

    blocks = []
    for h2 in h2_tags:
        link = h2.find("a", href=re.compile(r"/movies/"))
        title = link.get_text(strip=True)
        movie_url = link["href"]
        if movie_url.startswith("/"):
            movie_url = BASE_URL + movie_url

        container = h2
        for _ in range(10):
            if container.parent is None:
                break
            container = container.parent
            txt = container.get_text(" ", strip=True)
            if "Run Time" in txt and "Please select a showtime" in txt:
                other_titles = {
                    a.get_text(strip=True)
                    for a in container.find_all("h2")
                    if a.find("a", href=re.compile(r"/movies/"))
                }
                if len(other_titles) <= 1:
                    break

        block_text = container.get_text(" ", strip=True)

        purchase_ids = []
        for a in container.find_all("a", href=re.compile(r"/purchase/\d+")):
            m = re.search(r"/purchase/(\d+)", a["href"])
            if m:
                purchase_ids.append(m.group(1))
        seen = set()
        purchase_ids = [p for p in purchase_ids if not (p in seen or seen.add(p))]

        runtime_match = re.search(r"Run Time:\s*(\d+)\s*min", block_text)
        runtime_min = int(runtime_match.group(1)) if runtime_match else None

        director_match = re.search(r"Director:\s*([^.]+?)(?:Run Time|Format|Rating|$)", block_text)
        director = director_match.group(1).strip() if director_match else None

        blocks.append(
            {
                "title": title,
                "movie_url": movie_url,
                "purchase_ids": purchase_ids,
                "runtime_min": runtime_min,
                "director": director,
            }
        )
    return blocks


def get_showtime_detail(purchase_id):
    """
    Visits a single /purchase/<id>/ page and returns
      { start: datetime (tz-aware, America/Los_Angeles), location: str }
    or None if the expected fields weren't found.
    """
    url = f"{BASE_URL}/purchase/{purchase_id}/"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    dt_match = re.search(
        r"Date\s*&\s*Time\D{0,10}([A-Za-z]{3},\s*[A-Za-z]{3}\s*\d{1,2}\s*@\s*\d{1,2}:\d{2}\s*[apAP][mM])",
        text,
    )
    if not dt_match:
        return None

    raw = dt_match.group(1)
    cleaned = re.sub(r"\s*@\s*", " ", raw)  # "Tue, Jul 7 7:00 pm"
    naive = datetime.strptime(cleaned, "%a, %b %d %I:%M %p")

    now = datetime.now()
    candidate = naive.replace(year=now.year)
    if (candidate - now).days < -60:
        candidate = candidate.replace(year=now.year + 1)
    start = candidate.replace(tzinfo=LA_TZ)

    auditorium_match = re.search(r"Auditorium\D{0,10}(\d+\s*-\s*[^\n]+)", text)
    if auditorium_match:
        location = f"Vidiots, {auditorium_match.group(1).strip()}, 4884 Eagle Rock Blvd, Los Angeles, CA 90041"
    else:
        location = "Vidiots, 4884 Eagle Rock Blvd, Los Angeles, CA 90041"

    return {"start": start, "location": location}


def escape_ics(text):
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_ics(events):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//justin//vidiots-calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    now_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    for ev in events:
        start_utc = ev["start"].astimezone(UTC)
        end_utc = start_utc + timedelta(minutes=ev.get("runtime_min") or DEFAULT_RUNTIME_MIN)
        uid = f"vidiots-{ev['purchase_id']}@justin-vidiots-calendar"

        desc_parts = []
        if ev.get("director"):
            desc_parts.append(f"Director: {ev['director']}")
        desc_parts.append(f"Details: {ev['movie_url']}")
        desc_parts.append(f"Tickets: {ev['purchase_url']}")
        description = "\n".join(desc_parts)

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{escape_ics(ev['title'])}",
            f"LOCATION:{escape_ics(ev['location'])}",
            f"DESCRIPTION:{escape_ics(description)}",
            f"URL:{ev['purchase_url']}",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    parser = argparse.ArgumentParser(description="Scrape Vidiots showtimes into an .ics feed")
    parser.add_argument("--out", default="vidiots.ics", help="Path to write the .ics file")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Parse and print what was found on the Coming Soon page, without "
        "hitting individual purchase pages or writing a file. Run this first.",
    )
    args = parser.parse_args()

    print(f"Fetching {COMING_SOON_URL} ...", file=sys.stderr)
    html = fetch(COMING_SOON_URL)
    blocks = get_movie_blocks(html)

    if not blocks:
        print(
            "No films found. The page structure likely differs from what this "
            "script expects -- see README's 'If it breaks' section.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.debug:
        print(f"Found {len(blocks)} films:\n")
        for b in blocks:
            print(f"- {b['title']}")
            print(f"    movie_url:  {b['movie_url']}")
            print(f"    runtime:    {b['runtime_min']} min")
            print(f"    director:   {b['director']}")
            print(f"    showtimes:  {len(b['purchase_ids'])} purchase link(s)")
        return

    events = []
    total_showtimes = sum(len(b["purchase_ids"]) for b in blocks)
    print(f"Found {len(blocks)} films, {total_showtimes} showtimes with ticket links. Resolving...", file=sys.stderr)

    done = 0
    for b in blocks:
        for pid in b["purchase_ids"]:
            done += 1
            purchase_url = f"{BASE_URL}/purchase/{pid}/"
            try:
                detail = get_showtime_detail(pid)
            except requests.RequestException as e:
                print(f"  [{done}/{total_showtimes}] {b['title']} #{pid}: request failed ({e}), skipping", file=sys.stderr)
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            if detail is None:
                print(f"  [{done}/{total_showtimes}] {b['title']} #{pid}: couldn't find date/time, skipping", file=sys.stderr)
            else:
                events.append(
                    {
                        "title": b["title"],
                        "movie_url": b["movie_url"],
                        "purchase_url": purchase_url,
                        "purchase_id": pid,
                        "runtime_min": b["runtime_min"],
                        "director": b["director"],
                        "start": detail["start"],
                        "location": detail["location"],
                    }
                )
            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Resolved {len(events)}/{total_showtimes} showtimes. Writing {args.out}", file=sys.stderr)
    ics_text = build_ics(events)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(ics_text)


if __name__ == "__main__":
    main()
