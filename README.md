# ⚡ NEXUS v5

**League Account Vault & Live Tracker** — store all your League of Legends accounts in one place and keep their ranks, stats, and match history up-to-date automatically. Great for players juggling multiple accounts — whether you grind solo queue on different roles, boost friends, or just like having alts.

> After the first login, NEXUS remembers everything. Click **Sync** anytime to pull your latest rank, LP gains, win/loss record, and top champion — no need to re-enter passwords ever again.



---

## 🤔 Why NEXUS?

Managing multiple League accounts is a pain. You either keep a messy spreadsheet, reuse passwords (bad idea), or just forget which account is at what rank. NEXUS solves this:

- **Store accounts securely** — encrypted, not in a `.txt` file on your desktop
- **One-click login** — no more typing passwords into the Riot Client
- **Auto-sync after login** — rank, LP, wins, losses, match history, and best champion all update without lifting a finger
- **Track your climb** — LP delta per session tells you if you're actually climbing or just treading water
- **At-a-glance dashboard** — open a browser tab and see every account's current state

## ✨ Features

- **🔐 Encrypted Credentials** — AES-256-GCM encryption for your entire account database. Passwords are never stored in plain text.
- **🤖 Automated Login** — Computer vision (via `pyautogui`) finds the Riot Client login fields, types your credentials, and clicks through to launch the game.
- **📊 Live Rank Sync** — Connects to the League Client Update (LCU) API to pull live stats: rank, LP, wins/losses, match history, and champion mastery.
- **📈 LP Delta Tracking** — Tracks LP gained or lost per session so you know exactly how your climb is going.
- **🔑 Token-Based API Auth** — All account management endpoints are protected by a session token (`x-nexus-token`) generated on first boot.
- **🗃️ Multi-Account Manager** — Store unlimited accounts with tags, notes, and full rank history.
- **🌐 Web Dashboard** — Dark cyberpunk-themed UI at `http://localhost:4000` with real-time updates.
- **🔓 Credential Decryptor** — `decrypt.py` lets you safely view or export credentials from the encrypted database.
- **⚡ Manual Sync** — Update rank data without re-logging — just have League open and hit sync.

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Node.js + Express |
| **Frontend** | HTML/CSS/JS (custom dark theme) |
| **Automation** | Python 3 (`pyautogui` for vision, `lcu-driver` for LCU API) |
| **Encryption** | AES-256-GCM (`crypto` in Node, `cryptography` in Python) |
| **Storage** | Encrypted JSON (`db.json`) |

## 🚀 Getting Started

### Prerequisites

- **Windows** (required — uses `tasklist`, `taskkill`, `pyautogui`)
- **Python 3.10+** with: `lcu-driver`, `pyautogui`, `psutil`, `cryptography`
- **Node.js 18+** (for the dashboard server)
- **League of Legends** installed

### Quick Install

1. **Clone the repo:**
   ```bash
   git clone https://github.com/wtfmiamia/NEXUS.git
   cd NEXUS
   ```

2. **Run the installer:**
   Double-click `install_nexus.bat` — installs all Python and Node.js dependencies automatically.

3. **Launch:**
   Run `start_nexus.bat` (as administrator) to start the dashboard at `http://localhost:4000`.

4. **Configure from the dashboard:**
   Open the Settings panel in the web UI to set your Riot Client path and region.

### Usage

1. Open the dashboard at `http://localhost:4000`
2. Add accounts via the **+** button (username, password, optional tags/notes)
3. Click **Login** on any account — the system will:
   - Gracefully kill existing Riot processes
   - Launch the Riot Client
   - Use image recognition to find and fill the login form
   - Click the Play button to launch League
   - Wait 20s for the client to load
   - Sync rank data from the LCU API

> **How the pieces connect:** When you click Login, `server.js` spawns `vision.py` as a child process. `vision.py` reads the encrypted database directly from disk, decrypts the password using the token in `config.json`, and automates the Riot Client. Once it signals success, the server waits for League to open, then spawns `lcu_sync.py` to pull live rank data from the LCU API and write it back to `db.json`.

## 🧠 How It Works

### Core Files

Three files do all the heavy lifting:

| File | Role | Reads | Writes |
|------|------|-------|--------|
| **`server.js`** | Orchestrator — Express API, spawns Python processes, handles encryption | `db.json`, `config.json` | `db.json` (encrypted), `config.json` |
| **`vision.py`** | Auto-login — computer vision to type credentials into Riot Client | `config.json` → token → decrypt `db.json` | — |
| **`lcu_sync.py`** | Rank sync — pulls live data from League Client API | `db.json` (reads current state) | `db.json` (writes updated stats) |

### Login Flow

1. **Graceful Nuke** — Attempts soft `taskkill`, then force-kills any lingering Riot processes
2. **Vision Phase** (`vision.py`) — Launches Riot Client, scans the screen for username field templates using `pyautogui`, types credentials, submits
3. **Play Detection** — Polls for the Play button image, clicks it to launch League
4. **LCU Sync** (`lcu_sync.py`) — After a 20s delay for the client to load, connects to the local LCU API and pulls live data
5. **Dashboard Update** — Encrypted data is saved to `db.json`, frontend polls `/api/update-signal` for changes

### Encryption Model

```
nexusToken (config.json)
    │
    └──▶ SHA-256(nexusToken) = 32-byte AES key
              │
              ├──▶ db.json ── encrypted as a single AES-256-GCM blob
              │
              └──▶ Individual passwords ── encrypted separately
                   (allows decrypting a single account without exposing the whole DB)
```

- **At-rest**: Full database is encrypted with AES-256-GCM
- **Per-password**: Each account's password gets its own IV + auth tag
- **Migration**: Legacy plain-text passwords auto-migrate on first read
- **No plaintext ever**: Passwords only exist as plaintext during the brief moment they're typed into the Riot Client

## 📡 API Reference

All `/api/accounts*` endpoints require the `x-nexus-token` header.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/token` | — | Get the session token |
| `GET` | `/api/config` | — | Get server config |
| `POST` | `/api/config` | — | Update config (token is preserved) |
| `GET` | `/api/accounts` | ✅ | List all accounts (encrypted at-rest) |
| `POST` | `/api/accounts` | ✅ | Add a new account |
| `PUT` | `/api/accounts/:index` | ✅ | Update an account |
| `DELETE` | `/api/accounts/:index` | ✅ | Remove an account |
| `POST` | `/api/login` | ✅ | Trigger auto-login sequence |
| `POST` | `/api/sync-only` | ✅ | Manual rank sync (League must be open) |
| `POST` | `/api/kill-riot` | ✅ | Force-close all Riot processes |
| `GET` | `/api/update-signal` | — | Poll for database updates (returns `lastUpdate`) |

## 📁 Project Structure

```
NEXUS/
├── server.js              # Express backend (encryption, API, login orchestration)
├── package.json           # Node.js dependencies
├── config.json            # Riot Client path, region, auto-generated nexusToken
├── db.json                # Encrypted account database
├── decrypt.py             # CLI tool to decrypt and view account credentials
├── public/
│   └── index.html         # Web dashboard frontend
├── src/
│   ├── vision.py          # Computer vision auto-login (pyautogui)
│   ├── lcu_sync.py        # LCU API rank sync (lcu-driver)
│   └── test.py            # Credential decryption/logging utility
├── assets/
│   ├── riot_icon.png      # Riot taskbar icon (refocus detection)
│   ├── username.png       # Username field template
│   ├── username_active.png # Active username field template
│   └── play_button.png    # Play button template
├── install_nexus.bat      # One-click dependency installer
└── start_nexus.bat        # Dashboard launcher (elevated privileges)
```

## 🔧 CLI Tools

### `decrypt.py` — View Decrypted Credentials

```bash
# Decrypt and display a single account
python decrypt.py 0

# Show all accounts
python decrypt.py all
```

### `src/test.py` — Decryption Sanity Check

Tests that password decryption is working correctly. Reads an account from the encrypted DB, decrypts its password, and prints the result. Useful for verifying the encryption pipeline after setup.

```bash
# Verify decryption works for account at index 0
python src/test.py 0
```

### `src/lcu_sync.py` — Standalone Sync

```bash
# Sync rank data for account at index 0 (League must be open)
python src/lcu_sync.py 0

# Identify the currently logged-in account
python src/lcu_sync.py IDENTIFY
```

## ⚠️ Important Notes

- **Admin rights required** — The dashboard must run elevated to kill Riot processes cleanly. `start_nexus.bat` requests elevation automatically.
- **Windows only** — Uses Windows-specific APIs (`tasklist`, `taskkill`, Win32 paths). No macOS/Linux support planned.
- **Image recognition** — Assets in `assets/` must match your Riot Client version. If the UI changes after a patch, update the template images.
- **Never share your `nexusToken`** — It's the encryption key for your entire database. Anyone with it can decrypt all your stored credentials.
- **Back up `config.json`** — If you lose the `nexusToken`, you lose access to all encrypted data. There is no recovery.
- **LCU API** — Sync requires League Client to be running and logged in. The script connects to the local LCU at `127.0.0.1`.

## 🔒 Security

- Passwords are encrypted with **AES-256-GCM** — authenticated encryption with integrity guarantees
- Each password blob contains its own IV, ciphertext, and authentication tag
- The full database is stored as a single encrypted JSON blob
- Legacy plain-text passwords are auto-migrated on first read — **zero-touch upgrade**
- API endpoints are protected by a session token generated on first boot


## 📄 License

[GNU GPL v3](LICENSE) © [Mia](https://github.com/wtfmiamia)

---

<p align="center">
  <i>Built for the grind. One account at a time. 🏆</i>
</p>
