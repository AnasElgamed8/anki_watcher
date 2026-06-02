#!/usr/bin/env python3
"""
Anki Watcher — Monitors a Syncthing-synced folder for new Anki cards
and pushes them to Anki via AnkiConnect.

Usage:
  python3 anki_watcher.py [--config /path/to/config.json] [--watch-dir /path/to/watch]

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

# --- Defaults (overridden by config.json) ---
DEFAULTS = {
    "anki_connect_url": "http://localhost:8765",
    "anki_connect_version": 6,
    "cards_filename": "new_cards.json",
    "default_deck_prefix": "Reading",
    "default_model": "Basic",
    "default_tags": ["reading"],
    "poll_interval_seconds": 30,
    "watch_dir": None,
}

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("anki-watcher")


def load_config(config_path: Path = None) -> dict:
    """Load config from file, falling back to defaults."""
    config = dict(DEFAULTS)

    # Find config file
    if config_path and config_path.exists():
        found = config_path
    else:
        # Search relative to script location
        script_dir = Path(__file__).parent
        candidates = [
            script_dir / "config.json",
            Path.home() / ".config" / "anki-watcher" / "config.json",
        ]
        found = next((c for c in candidates if c.exists()), None)

    if found:
        try:
            user_config = json.loads(found.read_text(encoding="utf-8"))
            # Merge: user values override defaults
            for key, value in user_config.items():
                if key in config:
                    config[key] = value
            log.info(f"Loaded config from {found}")
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load config from {found}: {e}. Using defaults.")
    else:
        log.info("No config file found. Using defaults.")

    return config


def resolve_watch_dir(config: dict, cli_override: str = None) -> Path:
    """Resolve the watch directory from CLI arg, config, or auto-detection."""
    # CLI arg takes priority
    if cli_override:
        return Path(cli_override)

    # Config value
    if config.get("watch_dir"):
        return Path(config["watch_dir"])

    # Auto-detect from common Obsidian vault locations
    candidates = [
        Path.home() / "Obsidian" / "AI" / "English" / "Anki",
        Path.home() / "obsidian" / "AI" / "English" / "Anki",
        Path("/opt/data/Obsidian/AI/English/Anki"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


class AnkiClient:
    """Client for AnkiConnect API."""

    def __init__(self, url: str, version: int):
        self.url = url
        self.version = version

    def request(self, action: str, params: dict = None) -> dict:
        """Send a request to AnkiConnect."""
        payload = {"action": action, "version": self.version}
        if params:
            payload["params"] = params

        try:
            resp = requests.post(self.url, json=payload, timeout=10)
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

    def ensure_deck(self, deck_name: str) -> bool:
        """Create a deck if it doesn't exist."""
        decks = self.request("deckNames")
        if decks is None:
            return False
        if deck_name in decks:
            return True
        result = self.request("createDeck", {"deck": deck_name})
        if result is not None:
            log.info(f"Created deck: {deck_name}")
            return True
        return False

    def note_exists(self, front: str, deck_name: str) -> bool:
        """Check if a note with this front text already exists."""
        query = f'deck:"{deck_name}" Front:"{front}"'
        result = self.request("findNotes", {"query": query})
        if result is None:
            return False
        return len(result) > 0

    def add_note(self, deck_name: str, front: str, back: str, tags: list, model: str = "Basic") -> bool:
        """Add a single note to Anki."""
        note = {
            "deckName": deck_name,
            "modelName": model,
            "fields": {"Front": front, "Back": back},
            "tags": tags,
            "options": {"allowDuplicate": False},
        }
        result = self.request("addNote", {"note": note})
        if result is not None:
            log.info(f"Added: '{front}' -> {deck_name}")
            return True
        return False

    def is_connected(self) -> bool:
        """Check if AnkiConnect is reachable."""
        return self.request("version") is not None


def process_cards(cards: list, client: AnkiClient, config: dict) -> dict:
    """Process a list of cards. Returns stats."""
    stats = {"total": len(cards), "added": 0, "skipped": 0, "failed": 0}

    for card in cards:
        deck = card.get("deck", f"{config['default_deck_prefix']}::Unknown")
        front = card.get("front", "").strip()
        back = card.get("back", "").strip()
        tags = card.get("tags", list(config["default_tags"]))
        model = config["default_model"]

        if not front or not back:
            log.warning(f"Skipping card with missing front/back: {card}")
            stats["failed"] += 1
            continue

        if not client.ensure_deck(deck):
            stats["failed"] += 1
            continue

        if client.note_exists(front, deck):
            log.info(f"Skipped (duplicate): '{front}'")
            stats["skipped"] += 1
            continue

        if client.add_note(deck, front, back, tags, model):
            stats["added"] += 1
        else:
            stats["failed"] += 1

    return stats


def check_and_process(watch_dir: Path, cards_filename: str, client: AnkiClient, config: dict):
    """Check for new cards and process them."""
    cards_file = watch_dir / cards_filename

    if not cards_file.exists():
        return

    try:
        content = cards_file.read_text(encoding="utf-8").strip()
        if not content or content == "[]":
            return
        cards = json.loads(content)
        if not isinstance(cards, list) or len(cards) == 0:
            cards_file.write_text("[]\n", encoding="utf-8")
            return
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in {cards_file}: {e}")
        return

    log.info(f"Found {len(cards)} new card(s) to process")
    stats = process_cards(cards, client, config)
    cards_file.write_text("[]\n", encoding="utf-8")

    log.info(
        f"Done: {stats['added']} added, {stats['skipped']} skipped (duplicates), "
        f"{stats['failed']} failed"
    )


def main():
    parser = argparse.ArgumentParser(description="Anki Watcher — Syncs cards from Syncthing to Anki")
    parser.add_argument("--config", type=str, default=None, help="Path to config.json")
    parser.add_argument("--watch-dir", type=str, default=None, help="Directory to watch for cards")
    parser.add_argument("--poll-interval", type=int, default=None, help="Seconds between checks")
    args = parser.parse_args()

    # Load config
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    # CLI overrides
    if args.poll_interval is not None:
        config["poll_interval_seconds"] = args.poll_interval

    # Resolve watch directory
    watch_dir = resolve_watch_dir(config, args.watch_dir)
    if watch_dir is None:
        log.error(
            "Could not find watch directory. "
            "Set 'watch_dir' in config.json or use --watch-dir"
        )
        sys.exit(1)

    # Init Anki client
    client = AnkiClient(config["anki_connect_url"], config["anki_connect_version"])

    log.info(f"Watching: {watch_dir}")
    log.info(f"Cards file: {config['cards_filename']}")
    log.info(f"Poll interval: {config['poll_interval_seconds']}s")
    log.info(f"Default deck prefix: {config['default_deck_prefix']}")
    log.info(f"Default model: {config['default_model']}")

    # Test connection on startup
    if client.is_connected():
        log.info("AnkiConnect connected")
    else:
        log.warning("AnkiConnect not reachable — will retry when Anki is open")

    # Main loop
    while True:
        try:
            check_and_process(watch_dir, config["cards_filename"], client, config)
            time.sleep(config["poll_interval_seconds"])
        except KeyboardInterrupt:
            log.info("Shutting down")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            time.sleep(config["poll_interval_seconds"])


if __name__ == "__main__":
    main()
