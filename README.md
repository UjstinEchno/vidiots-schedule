# Vidiots → Google Calendar feed

Scrapes https://vidiotsfoundation.org/coming-soon/ into an `.ics` file you can
subscribe to in Google Calendar, refreshed automatically once a day via
GitHub Actions + GitHub Pages.

Vidiots doesn't publish its own calendar feed (their site runs on the
Filmbot ticketing platform, which doesn't offer one), so this rebuilds one
from the public showtimes pages.

## How it works

1. `scrape_vidiots.py` reads the Coming Soon page for each film's title and
   showtime ("purchase") links, then visits each showtime's own ticket page
   to get its exact date/time/auditorium (the Coming Soon page alone doesn't
   cleanly say which time goes with which date for films with several
   showtimes across several days — the individual ticket page does).
2. It writes everything to `docs/vidiots.ics`.
3. A GitHub Action runs that script once a day and commits the updated file.
4. GitHub Pages serves `docs/vidiots.ics` at a public URL.
5. Google Calendar subscribes to that URL and refreshes periodically.

## One-time setup

1. **Create a new GitHub repo** (must be public — Pages + Google Calendar
   both need to fetch the file over a plain public URL). Push these files
   to it.

2. **Sanity-check the parser before trusting it.** Run:

   ```
   pip install -r requirements.txt
   python scrape_vidiots.py --debug
   ```

   This prints the films and showtime counts it found, without touching any
   purchase pages or writing a file. If it finds 0 films, or the counts look
   wrong, see "If it breaks" below before going further.

3. **Generate a real feed once, locally**, to confirm the whole pipeline
   works end to end:

   ```
   python scrape_vidiots.py --out docs/vidiots.ics
   ```

   Open the resulting file and skim it — check a few dates/times against
   the actual site.

4. Commit and push `docs/vidiots.ics`.

5. **Turn on GitHub Pages**: repo Settings → Pages → Deploy from branch →
   `main`, folder `/docs`.

6. Your feed URL will be:
   `https://<your-username>.github.io/<repo-name>/vidiots.ics`

7. **In Google Calendar**: Settings → Add calendar → From URL → paste that
   link.

Google typically refreshes subscribed URL calendars roughly every
12–24 hours — there's no setting to force it faster, and this is a Google
limitation, not something the daily GitHub Action can fix. The Action
running daily just makes sure the source file is fresh whenever Google does
check in.

## If it breaks

This was built by inspecting a text-rendered view of Vidiots' pages, not
the raw HTML source directly, so the parsing logic is my best inference
about the page structure rather than something verified against the live
site. `test_offline.py` checks the parsing logic against synthetic HTML
shaped like what I expect the real page to look like — it passing means the
*logic* is sound, not that it matches the real DOM exactly.

Most likely failure points, in order of likelihood:

- **`get_movie_blocks` finds 0 films** — the "climb up to find a
  self-contained card" heuristic in `scrape_vidiots.py` didn't find a
  container with both "Run Time" and "Please select a showtime" text. Open
  the page's real HTML source (right-click → View Page Source, or
  `curl https://vidiotsfoundation.org/coming-soon/ > page.html`) and check
  what text actually surrounds each film block; adjust the marker strings
  in `get_movie_blocks`.
- **Runtime or director show up as `None`** — the regexes expect
  `"Director: X Run Time: N min."` on one line; if the real markup adds
  extra tags in between, loosen the regex or extract from the movie's own
  page instead of the Coming Soon page.
- **`get_showtime_detail` returns `None` for every showtime** — the
  `"Date & Time"` and `"Auditorium"` label text I found on one ticket page
  might be formatted slightly differently elsewhere (e.g. different
  whitespace, or wrapped in something the text extraction handles
  differently than what I saw). Print `text` inside that function for one
  purchase ID and compare against the regex.

Feel free to paste me the actual error output or a snippet of the real page
source if something doesn't line up — I can adjust the regexes directly.

## Etiquette

The script waits ~0.6s between requests and identifies itself with a
descriptive User-Agent. Running it once a day for personal use is a light
footprint, but it isn't an official Vidiots integration — if their site
redesigns, this will need updating, and if they ever publish a real feed,
use that instead.
