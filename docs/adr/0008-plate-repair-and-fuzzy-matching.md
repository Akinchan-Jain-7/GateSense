# ADR-0008: Repairing OCR plate reads and matching them to known plates

- **Status:** Accepted (pending owner review in the Phase 2 PR)
- **Date:** 2026-11-21

## Context

OCR confuses characters that look alike (O/0, I/1, B/8, S/5, Z/2, G/6, T/7, A/4). The
brief asks for fixes applied *by position* (letters vs digits) and a fuzzy match against
known plates with a bounded edit distance. The difficulty is that an Indian plate's
layout is not fixed-width: `DL3CAB1234` (1-digit district, 3-letter series) and
`KA05MN0042` (2-digit district, 2-letter series) are both valid, so "position 4 is a
letter" isn't true for every plate.

## Decision

1. **Try every valid layout.** Standard plates are state (2 letters) + district (1–2
   digits) + series (0–3 letters) + number (1–4 digits); BH plates are year (2) + `BH` +
   number (4) + 1–2 letters. For each layout of the right length, a character of the wrong
   kind is swapped for its look-alike (cost 1); one with no look-alike rules the layout out.
2. **Score = fixes + small shape penalties** for legal but uncommon shapes (3-digit
   numbers, 1- or 3-letter series, 1-digit districts). The lowest score wins. Example:
   `KAO5MNOO42` reads as `KA05MN0042` (3 fixes, normal shape) rather than `KA05MNO042`
   (2 fixes, but a 3-letter series and a 3-digit number).
3. **Real-world constraints prune guesses:** the state code must be a real state/UT code
   (`0L…` → `DL…`, not `OL…`), and a fix may never produce I, O or Q in a series, because
   RTOs don't issue those letters there. More than 3 fixes → unreadable.
4. A leading **`IND`** (printed on high-security plates) is ignored if OCR includes it.
5. **Fuzzy matching:** Levenshtein distance ≤ `PLATE_FUZZY_MAX_DISTANCE` (default 1) against
   the society's active vehicles, active watchlist entries, and visits expected at that lane.
   The database pre-filters by plate length; distance is computed in Python with an early
   exit once the bound is exceeded. Exact matches always win. **Two equally close plates
   → no guess**: the event goes to the review queue as `ambiguous_match`.
6. **Order of checks:** watchlist first (even for low-confidence reads: a false alarm is
   cheap, a missed one isn't) → low confidence or unreadable → review queue, nothing
   automatic → resident vehicle → expected visitor → unknown.

## Alternatives considered

- **A single regex with character classes** (`[A-Z0O]` etc.). Can't express "this
  position is a letter only if the district has 2 digits". Rejected.
- **Pick the first layout that fits.** Order-dependent and silently wrong for ambiguous
  reads like `KAO5MNOO42`. Rejected.
- **Weighted edit distance** (cheaper substitutions for look-alikes). Mostly redundant once
  reads are repaired by position, and harder to explain. Rejected for v1.
- **Postgres `pg_trgm` / `levenshtein()`** for fuzzy search. Needs extensions and is
  overkill for a few hundred plates per society; the length pre-filter keeps the Python
  side small. Revisit if a society has tens of thousands of vehicles.
- **Distance 2.** Plates differ from each other by one or two characters often enough
  (`UP16AB1234` / `UP16AB1243`) that distance 2 would cause wrong matches. Rejected.

## Consequences

- 50 table-driven plate reads (41 repairable, 9 unreadable) plus 9 edit-distance cases pin
  the behaviour (`tests/unit/test_plate_reader.py`); changing a
  penalty must keep them passing.
- Requiring a real state code means a plate with a typo in the state can't be saved by an
  admin, which is the point.
- Real-world OCR accuracy is measured in Phase 3; the penalties may be tuned then.
