# Anki Watcher — Setup Guide

## What This Does
The cron job on the server processes your book vocabulary nightly and writes `new_cards.json` to your Obsidian folder. Syncthing syncs it to your local machine. This script watches for that file and pushes the cards into Anki via AnkiConnect.

**Result:** You open Anki → cards are already there.

## Prerequisites
- Anki Desktop installed and running (sometimes)
- AnkiConnect add-on installed in Anki (`Tools → Add-ons → Get Add-ons → Code: 2055492159`)
- Python 3.8+ (`python3 --version`)
- Syncthing syncing your Obsidian vault

## One-Time Setup (on your local machine)

### 1. Install the dependency
```bash
pip install requests
```

### 2. Copy the watcher script
Copy `anki_watcher.py` to your local Obsidian vault:
```bash
# From the projects folder, copy to your synced Obsidian directory
cp anki_watcher.py ~/Obsidian/AI/English/Anki/anki_watcher.py
```
(Adjust the path if your Obsidian vault is in a different location)

### 3. Test it manually
```bash
python3 ~/Obsidian/AI/English/Anki/anki_watcher.py
```
You should see:
```
Watching: /home/YOU/Obsidian/AI/English/Anki
Poll interval: 30s
Waiting for cards...
```
Open Anki, then create a test card:
```bash
echo '[{"deck": "Reading::Test", "front": "hello", "back": "Definition: a greeting", "tags": ["test"]}]' > ~/Obsidian/AI/English/Anki/new_cards.json
```
Within 30 seconds, the card should appear in Anki. Press Ctrl+C to stop.

### 4. Set up the systemd service (auto-start)
```bash
# Copy the service file
cp anki-watcher.service ~/.config/systemd/user/anki-watcher.service

# Edit the ExecStart path if your Obsidian vault is not at ~/Obsidian
# The %h variable = your home directory

# Enable and start
systemctl --user daemon-reload
systemctl --user enable anki-watcher.service
systemctl --user start anki-watcher.service

# Check status
systemctl --user status anki-watcher.service
```

### 5. Verify
```bash
# Check logs
journalctl --user -u anki-watcher -f
```

## How It Works
```
Server (11:30 PM)          Syncthing           Your Machine
┌─────────────────┐       ┌───────┐       ┌──────────────────┐
│ Cron processes   │──────▶│ Sync  │──────▶│ new_cards.json   │
│ vocab, writes    │       │       │       │ appears in       │
│ new_cards.json   │       └───────┘       │ Obsidian folder  │
└─────────────────┘                        └────────┬─────────┘
                                                    │
                                         anki_watcher.py detects it
                                                    │
                                                    ▼
                                         ┌──────────────────┐
                                         │ AnkiConnect API  │
                                         │ (localhost:8765)  │
                                         └────────┬─────────┘
                                                    │
                                                    ▼
                                         ┌──────────────────┐
                                         │ Cards appear      │
                                         │ in Anki!          │
                                         └──────────────────┘
```

## Troubleshooting

### "Cannot connect to AnkiConnect"
- Make sure Anki is open
- Make sure AnkiConnect add-on is installed (`Tools → Add-ons`)
- AnkiConnect runs on `http://localhost:8765`

### Cards not appearing
- Check if `new_cards.json` exists in `~/Obsidian/AI/English/Anki/`
- Check watcher logs: `journalctl --user -u anki-watcher -f`
- Verify the JSON is valid: `python3 -c "import json; json.load(open('new_cards.json'))"`

### Systemd service not starting
- Check if the path in the service file matches your Obsidian vault location
- `systemctl --user status anki-watcher.service` for error details
- Make sure `requests` is installed for the system Python: `python3 -c "import requests"`
