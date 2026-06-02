#!/usr/bin/env python3
"""
Anki Watcher — Monitors a Syncthing-synced folder for new Anki cards
and pushes them to Anki via AnkiConnect.

Usage:
  python3 anki_watcher.py [--watch-dir /path/to/watch] [--poll-interval 30]

Expects new_cards.json in the watch directory with this structure:
[
  {
    "deck": "Reading::Crime and Punishment",
    "front": "solace",
    "back": "Definition: comfort or consolation...",
    "tags": ["reading", "crime-and-punishment"]
  }
]

After processing, the file is cleared to [].
"""

import json
import time
import argparse
import logging
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found. Install with: pip install requests")
    sys.exit(1)

# --- Config ---
ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_CONNECT_VERSION = 6

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("anki-watcher")


def anki_request(action: str, params: dict = None) -> dict:
    """Send a request to AnkiConnect."""
    payload = {
        "action": action,
        "version": ANKI_CONNECT_VERSION,
    }
    if params:
        payload["params"] = params

    try:
        resp = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            log.error(f"AnkiConnect error ({action}): {result['error']}")
            return None
        return result.get("result")
    except requests.ConnectionError:
        log.warning("Cannot connect to AnkiConnect — is Anki running?")
        return None
    except Exception as e:
        log.error(f"AnkiConnect request failed ({action}): {e}")
        return None


def ensure_deck_exists(deck_name: str) -> bool:
    """Create a deck (and any parent decks) if it doesn't exist."""
    result = anki_request("deckNames")
    if result is None:
        return False

    if deck_name in result:
        return True

    result = anki_request("createDeck", {"deck": deck_name})
    if result is not None:
        log.info(f"Created deck: {deck_name}")
        return True
    return False


def note_exists(front: str, deck_name: str) -> bool:
    """Check if a note with this front text already exists in the deck."""
    # Search for notes with matching front field
    query = f'deck:"{deck_name}" Front:"{front}"'
    result = anki_request("findNotes", {"query": query})
    if result is None:
        return False
    return len(result) > 0


def add_note(deck_name: str, front: str, back: str, tags: list) -> bool:
    """Add a single note to Anki."""
    note = {
        "deckName": deck_name,
        "modelName": "Basic",
        "fields": {
            "Front": front,
            "Back": back,
        },
        "tags": tags,
        "options": {
            "allowDuplicate": False,
        },
    }
    result = anki_request("addNote", {"note": note})
    if result is not None:
        log.info(f"Added: '{front}' → {deck_name}")
        return True
    return False


def process_cards(cards: list) -> dict:
    """Process a list of cards. Returns stats."""
    stats = {"total": len(cards), "added": 0, "skipped": 0, "failed": 0}

    for card in cards:
        deck = card.get("deck", "Reading::Unknown")
        front = card.get("front", "").strip()
        back = card.get("back", "").strip()
        tags = card.get("tags", ["reading"])

        if not front or not back:
            log.warning(f"Skipping card with missing front/back: {card}")
            stats["failed"] += 1
            continue

        # Ensure deck exists
        if not ensure_deck_exists(deck):
            stats["failed"] += 1
            continue

        # Check for duplicate
        if note_exists(front, deck):
            log.info(f"Skipped (duplicate): '{front}'")
            stats["skipped"] += 1
            continue

        # Add the note
        if add_note(deck, front, back, tags):
            stats["added"] += 1
        else:
            stats["failed"] += 1

    return stats


def clear_file(filepath: Path):
    """Clear the JSON file to an empty array."""
    filepath.write_text("[]\n", encoding="utf-8")


def check_and_process(watch_dir: Path):
    """Check for new cards and process them."""
    cards_file = watch_dir / "new_cards.json"

    if not cards_file.exists():
        return

    try:
        content = cards_file.read_text(encoding="utf-8").strip()
        if not content or content == "[]":
            return

        cards = json.loads(content)
        if not isinstance(cards, list) or len(cards) == 0:
            clear_file(cards_file)
            return

    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in {cards_file}: {e}")
        return

    log.info(f"Found {len(cards)} new card(s) to process")

    # Process
    stats = process_cards(cards)

    # Clear the file after processing
    clear_file(cards_file)

    # Log summary
    log.info(
        f"Done: {stats['added']} added, {stats['skipped']} skipped (duplicates), "
        f"{stats['failed']} failed"
    )


def main():
    parser = argparse.ArgumentParser(description="Anki Watcher — Syncs cards from Syncthing to Anki")
    parser.add_argument(
        "--watch-dir",
        type=str,
        default=None,
        help="Directory to watch for new_cards.json (auto-detected from Obsidian vault)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Seconds between checks (default: 30)",
    )
    args = parser.parse_args()

    # Auto-detect watch directory
    if args.watch_dir:
        watch_dir = Path(args.watch_dir)
    else:
        # Try common Obsidian vault locations
        candidates = [
            Path.home() / "Obsidian" / "AI" / "English" / "Anki",
            Path.home() / "obsidian" / "AI" / "English" / "Anki",
            Path("/opt/data/Obsidian/AI/English/Anki"),
        ]
        watch_dir = None
        for candidate in candidates:
            if candidate.exists():
                watch_dir = candidate
                break

        if watch_dir is None:
            log.error(
                "Could not auto-detect Obsidian vault. "
                "Run with --watch-dir /path/to/Obsidian/AI/English/Anki"
            )
            sys.exit(1)

    log.info(f"Watching: {watch_dir}")
    log.info(f"Poll interval: {args.poll_interval}s")
    log.info("Waiting for cards...")

    # Test AnkiConnect connection on startup
    result = anki_request("version")
    if result is None:
        log.warning("AnkiConnect not reachable — will retry when Anki is open")
    else:
        log.info(f"AnkiConnect v{result} connected")

    # Main loop
    while True:
        try:
            check_and_process(watch_dir)
            time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            log.info("Shutting down")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
