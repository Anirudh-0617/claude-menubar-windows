# Claude Counter — Windows System Tray App 🪙

A native Windows system tray app that shows your live Claude token usage, session/weekly limits, and estimated cost — works directly with the **Claude desktop app**, no browser needed.

```
🪙 (tray icon)    ← lives in your Windows system tray (bottom-right)

Hover to see:
  Tokens: ~14,200 / 200,000  (7.1%)
  ↑ 9.8k in  ↓ 4.4k out
  Est. cost (Sonnet): $0.0042

  Session (5h):  27.0%   resets in 3h 43m
  Weekly  (7d):  25.0%   resets in 6d 6h
```

---

## Requirements

- Windows 10 or 11
- Python 3.9+  — download from [python.org](https://python.org)
- [Claude desktop app](https://claude.ai/download) installed and signed in at least once

---

## Installation

```bat
git clone https://github.com/Anirudh-0617/claude-menubar-windows.git
cd claude-menubar-windows
install.bat
```

The installer will:
1. Create a Python virtual environment
2. Install all dependencies
3. Build a standalone `.exe` with PyInstaller
4. Copy it to your Startup folder (auto-launches on login)
5. Launch it immediately

---

## Updating

```bat
cd claude-menubar-windows
rebuild.bat
```

---

## Troubleshooting

If the tray icon shows an error or doesn't update:

```bat
cd claude-menubar-windows
venv\Scripts\python diagnose.py
```

Or check the log file:
```
%TEMP%\claude_counter_win.log
```

`diagnose.py` tests each step: Local State → DPAPI decrypt → cookie decryption → API call.

---

## How It Works

```
Windows System Tray App
  │
  ├── Reads: %APPDATA%\Claude\Local State (JSON)
  │         → extracts AES key encrypted with Windows DPAPI
  │         → CryptUnprotectData() decrypts it (no password needed)
  │
  ├── Reads: %APPDATA%\Claude\Cookies (SQLite)
  │         → AES-256-GCM decrypt with key above
  │         → extracts session token + org ID
  │
  ├── HTTP via curl_cffi — impersonates Chrome124 TLS fingerprint
  │         → bypasses Cloudflare bot protection
  │
  ├── GET /api/organizations/{org}/usage
  │         → five_hour + seven_day utilization %
  │
  └── GET /api/organizations/{org}/chat_conversations/{id}
            → message tree → token count heuristic
```

**Windows vs macOS encryption:**

| | macOS | Windows |
|--|-------|---------|
| Key storage | macOS Keychain | Windows DPAPI (Local State file) |
| Key derivation | PBKDF2-SHA1 | Direct DPAPI decrypt |
| Cookie cipher | AES-128-CBC | AES-256-GCM |
| Cookie prefix | `v10` + backtick header | `v10` + nonce + ciphertext + tag |

---

## Files

| File | Purpose |
|------|---------|
| `claude_counter_win.py` | Main app — system tray, cookie decrypt, API, UI |
| `requirements.txt` | Python dependencies |
| `install.bat` | First-time setup |
| `rebuild.bat` | Update & reinstall |
| `diagnose.py` | Step-by-step debug tool |

---

## Privacy

Fully local — reads your own cookies from your own PC and calls `claude.ai` directly with your session. No external servers, no analytics, no tracking.

---

## Also Check Out

- macOS menu bar version → [github.com/Anirudh-0617/claude-menubar](https://github.com/Anirudh-0617/claude-menubar)
- Chrome extension → [github.com/Anirudh-0617/claude-counter-mac](https://github.com/Anirudh-0617/claude-counter-mac)

---

## Credits

Inspired by [claude-counter](https://github.com/she-llac/claude-counter) by she-llac.
Built by [Anirudh-0617](https://github.com/Anirudh-0617).

## License

MIT
