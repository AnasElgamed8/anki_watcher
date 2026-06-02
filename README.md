# Anki Watcher

A lightweight bridge between Syncthing and Anki. Watches a synced folder for dated vocabulary card files and pushes them to Anki via AnkiConnect.

## How It Works

```
Server (cron job)         Syncthing            Your Machine
┌─────────────────┐      ┌───────┐       ┌──────────────────────┐
│ Processes vocab, │─────▶│ Sync  │─────▶│ new_cards_2026-06-02 │
│ writes dated     │      └───────┘       │ .json appears in     │
│ card files       │                      │ Obsidian folder      │
└─────────────────┘                      └──────────┬───────────┘
                                                    │
                                         anki_watcher.py detects it
                                                    │
                                                    ▼
                                         ┌──────────────────────┐
                                         │ AnkiConnect API      │
                                         │ (127.0.0.1:8765)      │
                                         └──────────┬───────────┘
                                                    │
                                                    ▼
                                         ┌──────────────────────┐
                                         │ Cards in Anki        │
                                         │ (archived)           │
                                         └──────────────────────┘
```

Each day gets its own file: `new_cards_YYYY-MM-DD.json`. The watcher processes all pending files and deletes each one after pushing to Anki. No race conditions, no overwriting, no lost cards.

## Prerequisites

- **Anki Desktop** installed ([ankiweb.net](https://apps.ankiweb.net/))
- **AnkiConnect** add-on (`Tools → Add-ons → Get Add-ons → Code: 2055492159`)
- **Python 3.8+**
- **Syncthing** syncing your Obsidian vault
- **requests** library (`pip install requests`)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/AnasElgamed8/anki_watcher.git
cd anki_watcher

# Install dependency
pip install requests

# Edit config.json to match your setup
nano config.json

# Run
python3 anki_watcher.py
```

## Configuration

All settings live in `config.json`:

```json
{
  "anki_connect_url": "http://127.0.0.1:8765",
  "anki_connect_version": 6,
  "cards_file_prefix": "new_cards_",
  "cards_file_extension": ".json",
  "default_deck_prefix": "Reading",
  "default_model": "Basic",
  "default_tags": ["reading"],
  "poll_interval_seconds": 30,
  "watch_dir": null
}
```

| Key | Description | Default |
|-----|-------------|---------|
| `anki_connect_url` | AnkiConnect API endpoint | `http://127.0.0.1:8765` |
| `anki_connect_version` | AnkiConnect protocol version | `6` |
| `cards_file_prefix` | Prefix for card files to watch | `new_cards_` |
| `cards_file_extension` | Extension for card files | `.json` |
| `default_deck_prefix` | Default parent deck name | `Reading` |
| `default_model` | Anki note type to use | `Basic` |
| `default_tags` | Tags applied to every card | `["reading"]` |
| `poll_interval_seconds` | How often to check for new cards | `30` |
| `watch_dir` | Absolute path to watch directory. `null` = auto-detect | `null` |

### Watch Directory Auto-Detection

If `watch_dir` is `null`, the script searches these locations in order:

1. `~/Obsidian/AI/English/Anki/`
2. `~/obsidian/AI/English/Anki/`
3. `/opt/data/Obsidian/AI/English/Anki/`

Override with `--watch-dir` CLI arg or set `watch_dir` in config.

## CLI Usage

```bash
# Use default config (auto-detect everything)
python3 anki_watcher.py

# Specify config file
python3 anki_watcher.py --config /path/to/config.json

# Override watch directory
python3 anki_watcher.py --watch-dir /path/to/Obsidian/AI/English/Anki

# Override poll interval
python3 anki_watcher.py --poll-interval 60
```

## Card Format

Cards are JSON objects in dated files (`new_cards_YYYY-MM-DD.json`):

```json
[
  {
    "deck": "Reading::Crime and Punishment",
    "front": "solace",
    "back": "Definition: comfort or consolation in a time of distress.\n\nUsage: \"He found solace in the quiet of the empty church.\"",
    "tags": ["reading", "crime-and-punishment"]
  }
]
```

| Field | Required | Description |
|-------|----------|-------------|
| `deck` | No | Full deck path. Uses `{default_deck_prefix}::Unknown` if omitted |
| `front` | Yes | The vocabulary word (card front) |
| `back` | Yes | Definition + usage example (card back) |
| `tags` | No | List of tags. Uses `default_tags` if omitted |

### Duplicate Handling

Before adding a card, the watcher queries AnkiConnect for existing notes with the same `Front` field in the same deck. If a match is found, the card is skipped.

## Systemd Service (Auto-Start)

Run the watcher as a background service that starts on boot:

```bash
# Copy files to your config directory
mkdir -p ~/.config/anki-watcher
cp config.json ~/.config/anki-watcher/config.json
cp anki_watcher.py ~/.config/anki-watcher/anki_watcher.py

# Edit the config for your local paths
nano ~/.config/anki-watcher/config.json

# Install the service
cp anki-watcher.service ~/.config/systemd/user/

# Edit the service file to point to your install
nano ~/.config/systemd/user/anki-watcher.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable anki-watcher.service
systemctl --user start anki-watcher.service

# Check status
systemctl --user status anki-watcher.service

# View logs
journalctl --user -u anki-watcher -f
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Cannot connect to AnkiConnect` | Make sure Anki is open and AnkiConnect is installed |
| Cards not appearing | Check if dated files exist in the Anki folder |
| `No config file found` | Copy `config.json` next to the script or to `~/.config/anki-watcher/` |
| Service won't start | Check `journalctl --user -u anki-watcher` for errors |
| Wrong watch directory | Set `watch_dir` explicitly in `config.json` |
| Old files piling up | Processed files are moved to `archive/`. If pending files remain, check logs for errors |

## Project Structure

```
anki_watcher/
├── anki_watcher.py       # Main script
├── config.json           # Configuration
├── anki-watcher.service  # systemd user service
└── README.md             # This file
```

## License

MIT
