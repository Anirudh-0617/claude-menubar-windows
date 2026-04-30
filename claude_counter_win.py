#!/usr/bin/env python3
"""
Claude Counter — Windows System Tray App
=========================================
Shows live Claude token usage in the Windows system tray.
Works with the Claude desktop app (Electron) — no browser needed.

Reads session cookies from Claude's Electron cookie store (SQLite).
Decrypts using Windows DPAPI + AES-256-GCM (same as Chrome on Windows).
Bypasses Cloudflare via curl_cffi Chrome TLS impersonation.

Requirements: pip install pystray pillow pycryptodome curl_cffi pywin32
"""

import os
import sys
import json
import math
import time
import shutil
import base64
import sqlite3
import tempfile
import threading
import re
from datetime import datetime, timezone
from pathlib import Path

# ── Windows DPAPI import ─────────────────────────────────────────────────────
try:
    import win32crypt
    HAS_DPAPI = True
except ImportError:
    HAS_DPAPI = False
    print("[WARN] pywin32 not installed — cookie decryption will fail")

# ── AES-GCM import ───────────────────────────────────────────────────────────
try:
    from Crypto.Cipher import AES
    HAS_AES = True
except ImportError:
    HAS_AES = False
    print("[WARN] pycryptodome not installed — cookie decryption will fail")

# ── curl_cffi for Cloudflare bypass ──────────────────────────────────────────
try:
    from curl_cffi import requests
    _SESSION_KWARGS = {"impersonate": "chrome124"}
    HAS_CFFI = True
except ImportError:
    import requests
    _SESSION_KWARGS = {}
    HAS_CFFI = False
    print("[WARN] curl_cffi not installed — API calls may get 403 from Cloudflare")

# ── pystray + PIL for system tray ─────────────────────────────────────────────
import pystray
from PIL import Image, ImageDraw, ImageFont

# ── Paths ─────────────────────────────────────────────────────────────────────
APPDATA         = os.environ.get("APPDATA", "")
COOKIE_DB       = os.path.join(APPDATA, "Claude", "Cookies")
LOCAL_STATE     = os.path.join(APPDATA, "Claude", "Local State")
LOG_FILE        = os.path.join(tempfile.gettempdir(), "claude_counter_win.log")
KEY_CACHE_FILE  = os.path.join(os.environ.get("USERPROFILE", ""), ".claude_counter_key.bin")

# ── Logging ───────────────────────────────────────────────────────────────────
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("claude_counter")

# ── Pricing ───────────────────────────────────────────────────────────────────
PRICING = {
    "haiku":  {"input": 0.80,  "output": 4.00},
    "sonnet": {"input": 3.00,  "output": 15.00},
    "opus":   {"input": 15.00, "output": 75.00},
}
CONTEXT_LIMIT = 200_000

# ─────────────────────────────────────────────────────────────────────────────
# Cookie Decryption (Windows DPAPI + AES-256-GCM)
# ─────────────────────────────────────────────────────────────────────────────

_aes_key_cache = None

def _get_aes_key() -> bytes | None:
    """Read AES key from Claude's Local State file, decrypt with DPAPI, cache it."""
    global _aes_key_cache
    if _aes_key_cache:
        return _aes_key_cache

    # Try disk cache first
    cache = Path(KEY_CACHE_FILE)
    if cache.exists():
        try:
            _aes_key_cache = cache.read_bytes()
            log.debug("Loaded AES key from disk cache")
            return _aes_key_cache
        except Exception:
            pass

    try:
        with open(LOCAL_STATE, "r", encoding="utf-8") as f:
            state = json.load(f)
        b64_key = state["os_crypt"]["encrypted_key"]
        encrypted_key = base64.b64decode(b64_key)
        # Strip "DPAPI" prefix (5 bytes)
        encrypted_key = encrypted_key[5:]
        # Decrypt with Windows DPAPI
        if not HAS_DPAPI:
            log.error("pywin32 not available — cannot decrypt key")
            return None
        _, key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)
        _aes_key_cache = key
        # Cache to disk
        cache.write_bytes(key)
        cache.chmod(0o600)
        log.info("AES key decrypted and cached")
        return key
    except Exception as e:
        log.error(f"Failed to get AES key: {e}")
        return None


def _decrypt_cookie(encrypted_value: bytes, key: bytes) -> str | None:
    """Decrypt a Chrome/Electron cookie value (v10 + AES-256-GCM)."""
    try:
        if not encrypted_value or len(encrypted_value) < 16:
            return None
        if encrypted_value[:3] != b"v10":
            # Unencrypted (rare)
            return encrypted_value.decode("utf-8", errors="ignore")
        # v10 | nonce (12 bytes) | ciphertext | tag (16 bytes)
        nonce      = encrypted_value[3:15]
        ciphertext = encrypted_value[15:-16]
        tag        = encrypted_value[-16:]
        if not HAS_AES:
            return None
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.decode("utf-8", errors="ignore")
    except Exception as e:
        log.debug(f"Cookie decrypt failed: {e}")
        return None


def get_claude_cookies() -> dict:
    """Read and decrypt all Claude cookies from Electron SQLite store."""
    if not os.path.exists(COOKIE_DB):
        log.error(f"Cookie DB not found: {COOKIE_DB}")
        return {}

    key = _get_aes_key()
    if not key:
        log.error("Cannot get AES key — aborting cookie read")
        return {}

    # Copy DB to temp file (avoid lock conflict with running Claude app)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    try:
        shutil.copy2(COOKIE_DB, tmp.name)
        con = sqlite3.connect(tmp.name)
        cur = con.cursor()
        cur.execute(
            "SELECT name, value, encrypted_value FROM cookies WHERE host_key LIKE '%claude%'"
        )
        rows = cur.fetchall()
        con.close()
    except Exception as e:
        log.error(f"SQLite error: {e}")
        return {}
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    cookies = {}
    for name, value, enc_val in rows:
        if enc_val:
            decrypted = _decrypt_cookie(enc_val, key)
            if decrypted:
                value = decrypted
        if value:
            # Sanitize: remove control chars that break HTTP headers
            clean = re.sub(r'[\x00-\x1f\x7f;,\\"]', '', str(value))
            try:
                clean.encode("ascii")
                cookies[name] = clean
            except UnicodeEncodeError:
                log.debug(f"Skipping non-ASCII cookie: {name}")
    log.info(f"Got {len(cookies)} Claude cookies")
    return cookies


# ─────────────────────────────────────────────────────────────────────────────
# Token Estimation
# ─────────────────────────────────────────────────────────────────────────────

def count_tokens(text: str) -> int:
    total = 0
    for word in re.findall(r'\S+', text):
        total += max(1, math.ceil(len(word) / 4))
    return math.ceil(total * 1.05)


def extract_text(msg: dict) -> str:
    parts = []
    for block in msg.get("content", []):
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            t = block.get("type", "")
            if t == "text":
                parts.append(block.get("text", ""))
            elif t in ("tool_use", "tool_result"):
                parts.append(json.dumps(block.get("input") or block.get("content") or ""))
    return " ".join(parts)


def build_trunk(conversation: dict) -> list:
    """Walk from leaf to root to get the active conversation branch."""
    msgs = {m["uuid"]: m for m in conversation.get("chat_messages", [])}
    leaf = conversation.get("current_leaf_message_uuid")
    trunk = []
    node = leaf
    while node and node in msgs:
        trunk.append(msgs[node])
        node = msgs[node].get("parent_message_uuid")
    return list(reversed(trunk))


def compute_tokens(conversation: dict) -> dict:
    trunk = build_trunk(conversation)
    input_t = output_t = 0
    for msg in trunk:
        t = count_tokens(extract_text(msg))
        if msg.get("sender") == "human":
            input_t += t
        else:
            output_t += t
    return {
        "total":  input_t + output_t,
        "input":  input_t,
        "output": output_t,
        "model":  conversation.get("model", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Claude API
# ─────────────────────────────────────────────────────────────────────────────

class ClaudeAPI:
    BASE = "https://claude.ai/api"

    def __init__(self):
        self._session = requests.Session(**_SESSION_KWARGS)

    def _headers(self, cookies: dict) -> dict:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return {
            "Cookie":          cookie_str,
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept":          "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         "https://claude.ai/",
            "sec-ch-ua":       '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile":"?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    def _org(self, cookies: dict) -> str | None:
        return cookies.get("lastActiveOrg")

    def get_usage(self, cookies: dict) -> dict | None:
        org = self._org(cookies)
        if not org:
            log.error("No lastActiveOrg cookie")
            return None
        try:
            r = self._session.get(
                f"{self.BASE}/organizations/{org}/usage",
                headers=self._headers(cookies), timeout=15,
            )
            log.info(f"Usage API: {r.status_code}")
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.error(f"Usage API error: {e}")
        return None

    def get_latest_conversation(self, cookies: dict) -> dict | None:
        org = self._org(cookies)
        if not org:
            return None
        try:
            r = self._session.get(
                f"{self.BASE}/organizations/{org}/chat_conversations?limit=1",
                headers=self._headers(cookies), timeout=15,
            )
            if r.status_code == 200:
                convs = r.json()
                if convs:
                    conv_id = convs[0]["uuid"]
                    return self.get_conversation(cookies, org, conv_id)
        except Exception as e:
            log.error(f"Conversations API error: {e}")
        return None

    def get_conversation(self, cookies: dict, org: str, conv_id: str) -> dict | None:
        try:
            r = self._session.get(
                f"{self.BASE}/organizations/{org}/chat_conversations/{conv_id}?rendering_mode=messages",
                headers=self._headers(cookies), timeout=15,
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.error(f"Conversation API error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# System Tray Icon
# ─────────────────────────────────────────────────────────────────────────────

def make_icon_image(pct: float, status: str = "ok") -> Image.Image:
    """Generate a tray icon — a small arc ring showing context usage."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    draw.ellipse([4, 4, size-4, size-4], fill=(40, 40, 40, 220))

    # Arc color by usage
    if pct >= 0.90:
        color = (220, 50, 50, 255)      # red
    elif pct >= 0.75:
        color = (240, 160, 30, 255)     # orange
    else:
        color = (80, 180, 255, 255)     # blue

    # Arc (0% = top, clockwise)
    arc_end = int(pct * 360) - 90
    if arc_end > -90:
        draw.arc([6, 6, size-6, size-6], start=-90, end=arc_end, fill=color, width=8)

    return img


# ─────────────────────────────────────────────────────────────────────────────
# App State
# ─────────────────────────────────────────────────────────────────────────────

class AppState:
    def __init__(self):
        self.tokens      = 0
        self.input_t     = 0
        self.output_t    = 0
        self.model       = "sonnet"
        self.five_hour   = 0.0
        self.seven_day   = 0.0
        self.five_reset  = ""
        self.seven_reset = ""
        self.last_update = None
        self.error       = None
        self.poll_interval = 30  # seconds

    @property
    def context_pct(self) -> float:
        return min(self.tokens / CONTEXT_LIMIT, 1.0)

    def est_cost(self) -> float:
        key = next((k for k in PRICING if k in self.model.lower()), "sonnet")
        p = PRICING[key]
        return (self.input_t / 1_000_000) * p["input"] + (self.output_t / 1_000_000) * p["output"]

    def status_emoji(self) -> str:
        pct = self.context_pct
        if pct >= 0.90: return "🔴"
        if pct >= 0.75: return "🟡"
        return "🟢"

    def fmt_reset(self, hours: float) -> str:
        if hours <= 0:
            return "soon"
        h = int(hours)
        m = int((hours - h) * 60)
        if h >= 24:
            return f"{h // 24}d {h % 24}h"
        return f"{h}h {m}m"


state = AppState()
api   = ClaudeAPI()


def refresh():
    """Fetch latest data from Claude API."""
    try:
        cookies = get_claude_cookies()
        if not cookies:
            state.error = "No Claude session found — open Claude desktop and sign in"
            return

        usage = api.get_usage(cookies)
        if usage:
            state.five_hour  = usage.get("five_hour", 0.0) * 100
            state.seven_day  = usage.get("seven_day", 0.0) * 100
            fh_reset = usage.get("five_hour_reset_in_hours", 0)
            sd_reset = usage.get("seven_day_reset_in_hours", 0)
            state.five_reset  = state.fmt_reset(fh_reset)
            state.seven_reset = state.fmt_reset(sd_reset)

        conv = api.get_latest_conversation(cookies)
        if conv:
            metrics = compute_tokens(conv)
            state.tokens   = metrics["total"]
            state.input_t  = metrics["input"]
            state.output_t = metrics["output"]
            state.model    = metrics.get("model", "sonnet")

        state.last_update = datetime.now()
        state.error = None
        log.info(f"Refreshed: {state.tokens} tokens, session {state.five_hour:.1f}%, week {state.seven_day:.1f}%")
    except Exception as e:
        state.error = str(e)
        log.error(f"Refresh error: {e}")


def poll_loop(icon):
    """Background polling thread."""
    while True:
        refresh()
        update_icon(icon)
        time.sleep(state.poll_interval)


def update_icon(icon):
    """Rebuild the tray icon and tooltip."""
    try:
        img = make_icon_image(state.context_pct)
        icon.icon = img

        if state.error:
            icon.title = f"🌑 Claude Counter — {state.error}"
        else:
            ago = ""
            if state.last_update:
                secs = int((datetime.now() - state.last_update).total_seconds())
                ago = f"  ·  updated {secs}s ago"
            icon.title = (
                f"🪙 Claude Counter  {state.status_emoji()}\n"
                f"Tokens: ~{state.tokens:,} / 200,000  ({state.context_pct*100:.1f}%)\n"
                f"↑ {state.input_t:,} in  ↓ {state.output_t:,} out\n"
                f"Est. cost ({state.model}): ${state.est_cost():.4f}\n"
                f"\n"
                f"Session (5h):  {state.five_hour:.1f}%   resets in {state.five_reset}\n"
                f"Weekly  (7d):  {state.seven_day:.1f}%   resets in {state.seven_reset}"
                f"{ago}"
            )
        icon.update_menu()
    except Exception as e:
        log.error(f"Icon update error: {e}")


def build_menu(icon):
    def refresh_now(icon, item):
        refresh()
        update_icon(icon)

    def quit_app(icon, item):
        icon.stop()

    return pystray.Menu(
        pystray.MenuItem(
            lambda item: (
                f"🌑 Error — check log" if state.error
                else f"Tokens: ~{state.tokens:,} / 200,000  ({state.context_pct*100:.1f}%)"
            ),
            None, enabled=False
        ),
        pystray.MenuItem(
            lambda item: f"  ↑ {state.input_t:,} in   ↓ {state.output_t:,} out",
            None, enabled=False
        ),
        pystray.MenuItem(
            lambda item: f"Est. cost ({state.model}): ${state.est_cost():.4f}",
            None, enabled=False
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            lambda item: f"Session (5h):  {state.five_hour:.1f}%   resets in {state.five_reset}",
            None, enabled=False
        ),
        pystray.MenuItem(
            lambda item: f"Weekly  (7d):  {state.seven_day:.1f}%   resets in {state.seven_reset}",
            None, enabled=False
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Refresh Now", refresh_now),
        pystray.MenuItem(
            lambda item: (
                f"Last updated {int((datetime.now() - state.last_update).total_seconds())}s ago · every {state.poll_interval}s"
                if state.last_update else "Not yet updated"
            ),
            None, enabled=False
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Claude Counter", quit_app),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log.info("Claude Counter starting...")
    log.info(f"curl_cffi: {HAS_CFFI}  |  DPAPI: {HAS_DPAPI}  |  AES: {HAS_AES}")

    # Initial icon (grey until first poll)
    img = make_icon_image(0.0)

    icon = pystray.Icon(
        name="claude_counter",
        icon=img,
        title="🪙 Claude Counter — loading...",
    )
    icon.menu = build_menu(icon)

    # Start polling in background
    t = threading.Thread(target=poll_loop, args=(icon,), daemon=True)
    t.start()

    icon.run()


if __name__ == "__main__":
    main()
