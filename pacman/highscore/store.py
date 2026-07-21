"""Persistent top-10 highscore table (subject V.5, PLAN.md Milestone 5.2).

A small, self-contained module: no dependency on the engine, UI, or
maze layers -- it stores ``(name, score)`` pairs in a JSON file and is
robust to every file fault the defense might throw at it. The design
mirrors the adversarial-config philosophy of the config loader:
loading NEVER raises. A missing file, unreadable file, malformed JSON,
wrong-shaped payload, or individual bad rows all degrade to "as many
valid entries as could be salvaged" (an empty table in the worst case),
never a traceback (subject III.1 / V.5 "robust to file errors").

Validation rules (subject V.5):
    * names: max ``MAX_NAME_LENGTH`` characters, alphanumeric and
      spaces only (surrounding whitespace trimmed first);
    * scores: non-negative integers;
    * the table keeps at most ``TOP_N`` entries, highest score first.
"""

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TOP_N = 10
MAX_NAME_LENGTH = 10
DEFAULT_NAME = "PLAYER"


@dataclass(frozen=True)
class HighscoreEntry:
    """One immutable ``(name, score)`` leaderboard row.

    Frozen so entries can live in the table without any risk of a
    caller mutating a stored score out from under the ordering.
    """

    name: str
    score: int


def sanitize_name(raw: str) -> str:
    """Coerce arbitrary text into a valid highscore name.

    Trims surrounding whitespace, drops every character that is not
    alphanumeric or an inner space, and truncates to
    ``MAX_NAME_LENGTH`` (subject V.5). Falls back to ``DEFAULT_NAME``
    when nothing valid survives, so a name is always displayable --
    the name-entry screen and the loader both route through here, so
    an empty or junk entry can never reach storage.
    """
    kept = [c for c in raw.strip() if c.isalnum() or c == " "]
    cleaned = "".join(kept)[:MAX_NAME_LENGTH].strip()
    return cleaned if cleaned else DEFAULT_NAME


def _coerce_score(raw: object) -> int | None:
    """Return a non-negative int score, or None if ``raw`` is invalid.

    Rejects bools (``True`` is an ``int`` subclass in Python, but a
    boolean is never a legitimate score) and anything non-integral or
    negative -- the row is dropped rather than clamped, since a
    corrupt score has no trustworthy "intended" value.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    if raw < 0:
        return None
    return raw


class HighscoreTable:
    """The top-10 leaderboard, sorted highest-first.

    Kept sorted and capped after every mutation, so ``entries`` is
    always presentation-ready for the main menu and the highscores
    screen. Construct directly for an empty table, or via
    :meth:`load` to read one from disk.
    """

    def __init__(self, entries: list[HighscoreEntry] | None = None) -> None:
        """Adopt ``entries`` (validated/sorted/capped) or start empty."""
        self._entries: list[HighscoreEntry] = []
        for entry in entries or []:
            self._entries.append(
                HighscoreEntry(sanitize_name(entry.name), entry.score)
            )
        self._normalize()

    @property
    def entries(self) -> list[HighscoreEntry]:
        """A copy of the ranked rows (highest score first, capped)."""
        return list(self._entries)

    def _normalize(self) -> None:
        """Sort by score descending (stable) and cap at ``TOP_N``.

        A stable sort means equal scores keep insertion order, so an
        earlier-achieved score outranks a later tie -- deterministic
        and matching the arcade's "first to the score wins the slot".
        """
        self._entries.sort(key=lambda entry: entry.score, reverse=True)
        del self._entries[TOP_N:]

    def qualifies(self, score: int) -> bool:
        """Whether ``score`` would earn a place on the board.

        True while the board has an empty slot, or once ``score``
        strictly beats the current lowest-ranked entry. Lets the UI
        decide up front whether to bother prompting for a name.
        """
        coerced = _coerce_score(score)
        if coerced is None:
            return False
        if len(self._entries) < TOP_N:
            return True
        return coerced > self._entries[-1].score

    def add(self, name: str, score: int) -> bool:
        """Insert one result; return whether it made the board.

        The name is sanitized and the score validated here, so callers
        may pass raw user input directly. A non-qualifying or invalid
        score is a no-op returning False; a bad score is dropped
        rather than stored as junk.
        """
        coerced = _coerce_score(score)
        if coerced is None or not self.qualifies(coerced):
            return False
        self._entries.append(
            HighscoreEntry(sanitize_name(name), coerced)
        )
        self._normalize()
        return True

    @classmethod
    def load(cls, path: str) -> "HighscoreTable":
        """Read a table from ``path``; never raise (subject V.5).

        Any fault -- missing/unreadable file, binary/invalid-UTF-8
        content, invalid JSON, a root that is not a list, rows that
        are not ``{"name", "score"}`` objects, or individual invalid
        scores -- is logged and skipped, salvaging whatever valid rows
        remain. The result is an empty table in the worst case, so
        game start is always safe.
        """
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            logger.info("No highscore file at %r yet; starting empty.", path)
            return cls()
        except OSError as exc:
            logger.warning("Could not read highscores %r (%s).", path, exc)
            return cls()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # A binary/invalid-UTF-8 file decodes during read(), raising
            # UnicodeDecodeError (a ValueError, NOT an OSError) -- catch
            # it alongside malformed JSON so a corrupt file degrades to
            # an empty table instead of crashing game start (V.5).
            logger.warning("Corrupt highscore file %r (%s).", path, exc)
            return cls()

        if not isinstance(payload, list):
            logger.warning(
                "Highscore file %r root is %s, not a list; ignoring.",
                path, type(payload).__name__,
            )
            return cls()

        salvaged: list[HighscoreEntry] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            score = _coerce_score(row.get("score"))
            name = row.get("name")
            if score is None or not isinstance(name, str):
                continue
            salvaged.append(HighscoreEntry(sanitize_name(name), score))
        return cls(salvaged)

    def save(self, path: str) -> bool:
        """Write the table to ``path`` as JSON; return success.

        Serialization failures (an unwritable directory, a full disk)
        are logged and reported as False rather than raised -- saving
        the leaderboard must never crash a finished game (subject
        V.5). Writes the ranked, capped rows exactly as displayed.
        """
        payload = [
            {"name": entry.name, "score": entry.score}
            for entry in self._entries
        ]
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except OSError as exc:
            logger.warning("Could not save highscores %r (%s).", path, exc)
            return False
        return True
