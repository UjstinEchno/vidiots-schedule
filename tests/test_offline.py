"""Offline sanity checks against synthetic HTML shaped like the real page,
plus unit tests of the date-parsing and ICS-building logic (no network)."""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "..")
import scrape_vidiots as sv

# --- synthetic "coming soon" style page (structure guess, two films) ---
FAKE_COMING_SOON = """
<html><body>
<div class="movie-card">
  <a href="/movies/the-furious/"><img src="poster.jpg"></a>
  <h2><a href="/movies/the-furious/">The Furious</a></h2>
  <p>Dates with showtimes for The Furious</p>
  <ul><li>Today, Jul 5</li><li>Tue, Jul 7</li><li>Wed, Jul 8</li></ul>
  <ol>
    <li>1:30 pm</li>
    <li>4:30 pm</li>
    <li><a href="/purchase/4297603/">7:00 pm</a></li>
    <li><a href="/purchase/4297605/">7:00 pm</a></li>
  </ol>
  <p>Please select a showtime button above to buy tickets.</p>
  <p>Director: Kenji Tanigaki Run Time: 113 min. Format: Digital Rating: R Release Year: 2026</p>
  <a href="/movies/the-furious/">See full details</a>
</div>
<div class="movie-card">
  <a href="/movies/top-gun/"><img src="poster2.jpg"></a>
  <h2><a href="/movies/top-gun/">Top Gun</a></h2>
  <p>Dates with showtimes for Top Gun</p>
  <ul><li>Mon, Jul 6</li></ul>
  <ol><li><a href="/purchase/4252666/">7:30 pm</a></li></ol>
  <p>Please select a showtime button above to buy tickets.</p>
  <p>Director: Tony Scott Run Time: 110 min. Format: Digital Rating: PG Release Year: 1986</p>
  <a href="/movies/top-gun/">See full details</a>
</div>
</body></html>
"""

blocks = sv.get_movie_blocks(FAKE_COMING_SOON)
assert len(blocks) == 2, f"expected 2 films, got {len(blocks)}"

furious = next(b for b in blocks if b["title"] == "The Furious")
assert furious["runtime_min"] == 113, furious
assert furious["director"] == "Kenji Tanigaki", furious
assert furious["purchase_ids"] == ["4297603", "4297605"], furious["purchase_ids"]

topgun = next(b for b in blocks if b["title"] == "Top Gun")
assert topgun["runtime_min"] == 110, topgun
assert topgun["purchase_ids"] == ["4252666"], topgun["purchase_ids"]
print("get_movie_blocks: OK ->", [(b['title'], b['purchase_ids']) for b in blocks])

# --- synthetic purchase page ---
FAKE_PURCHASE_PAGE = """
<html><body>
<div>Movie The Furious</div>
<div>Date & Time Tue, Jul 7 @ 7:00 pm</div>
<div>Auditorium 2 - Vidiots' intimate 35-seat microcinema</div>
<div>Rating R</div>
</body></html>
"""
# monkeypatch fetch() so get_showtime_detail doesn't hit the network
sv.fetch = lambda url: FAKE_PURCHASE_PAGE
detail = sv.get_showtime_detail("4297603")
assert detail is not None, "detail parse failed"
assert detail["start"].hour == 19 and detail["start"].minute == 0, detail["start"]
assert detail["start"].tzinfo is not None
assert "microcinema" in detail["location"].lower()
print("get_showtime_detail: OK ->", detail)

# --- ICS building ---
events = [{
    "title": "The Furious",
    "movie_url": "https://vidiotsfoundation.org/movies/the-furious/",
    "purchase_url": "https://vidiotsfoundation.org/purchase/4297603/",
    "purchase_id": "4297603",
    "runtime_min": 113,
    "director": "Kenji Tanigaki",
    "start": detail["start"],
    "location": detail["location"],
}]
ics_text = sv.build_ics(events)
assert "BEGIN:VEVENT" in ics_text
assert "SUMMARY:The Furious" in ics_text
assert "UID:vidiots-4297603@justin-vidiots-calendar" in ics_text
assert "DTSTART:" in ics_text and "DTEND:" in ics_text
print("build_ics: OK\n")
print(ics_text)
