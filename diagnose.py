#!/usr/bin/env python3
"""
diagnose.py — Claude Counter Windows Troubleshooter
Run this when the tray app isn't working:
  python diagnose.py
"""
import os, sys, json, base64, sqlite3, shutil, tempfile, re, math

APPDATA     = os.environ.get("APPDATA", "")
COOKIE_DB   = os.path.join(APPDATA, "Claude", "Cookies")
LOCAL_STATE = os.path.join(APPDATA, "Claude", "Local State")

def sep(title):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print('─'*50)

# ── Step 1: Check files exist ─────────────────────────────────
sep("Step 1 — Claude desktop files")
for path in [COOKIE_DB, LOCAL_STATE]:
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"  ✓ {path}  ({size:,} bytes)")
    else:
        print(f"  ✗ NOT FOUND: {path}")
        print("    → Open Claude desktop app and sign in, then re-run this.")

# ── Step 2: Read Local State ──────────────────────────────────
sep("Step 2 — Read Local State (AES key)")
try:
    with open(LOCAL_STATE, "r", encoding="utf-8") as f:
        state = json.load(f)
    b64 = state["os_crypt"]["encrypted_key"]
    enc_key = base64.b64decode(b64)
    print(f"  ✓ Found encrypted_key ({len(enc_key)} bytes)")
    print(f"    Prefix: {enc_key[:5]}  (should be b'DPAPI')")
except Exception as e:
    print(f"  ✗ Failed: {e}")
    sys.exit(1)

# ── Step 3: DPAPI decrypt ─────────────────────────────────────
sep("Step 3 — DPAPI decryption (pywin32)")
try:
    import win32crypt
    raw = enc_key[5:]  # strip DPAPI prefix
    _, key = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
    print(f"  ✓ AES key decrypted: {len(key)} bytes")
except ImportError:
    print("  ✗ pywin32 not installed. Run: pip install pywin32")
    sys.exit(1)
except Exception as e:
    print(f"  ✗ DPAPI failed: {e}")
    sys.exit(1)

# ── Step 4: Read + decrypt cookies ───────────────────────────
sep("Step 4 — Cookie decryption (AES-256-GCM)")
try:
    from Crypto.Cipher import AES
except ImportError:
    print("  ✗ pycryptodome not installed. Run: pip install pycryptodome")
    sys.exit(1)

def decrypt(enc_val, key):
    if enc_val[:3] != b"v10":
        return enc_val.decode("utf-8", errors="ignore")
    nonce = enc_val[3:15]
    ct    = enc_val[15:-16]
    tag   = enc_val[-16:]
    return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag).decode("utf-8", errors="ignore")

tmp = tempfile.mktemp(suffix=".db")
shutil.copy2(COOKIE_DB, tmp)
con = sqlite3.connect(tmp)
rows = con.execute("SELECT name, value, encrypted_value FROM cookies WHERE host_key LIKE '%claude%'").fetchall()
con.close()
os.unlink(tmp)

cookies = {}
for name, val, enc in rows:
    if enc:
        try:
            val = decrypt(enc, key)
        except Exception as e:
            print(f"  ✗ Decrypt failed for {name}: {e}")
            continue
    if val:
        clean = re.sub(r'[\x00-\x1f\x7f;,\\"]', '', str(val))
        try:
            clean.encode("ascii")
            cookies[name] = clean
        except UnicodeEncodeError:
            pass

print(f"  ✓ Decrypted {len(cookies)} cookies")
for name in ["lastActiveOrg", "sessionKey", "cf_clearance"]:
    v = cookies.get(name, "NOT FOUND")
    preview = v[:40] + "..." if len(v) > 40 else v
    print(f"    {name}: {preview}")

if "lastActiveOrg" not in cookies:
    print("\n  ✗ lastActiveOrg missing — sign into Claude desktop first")
    sys.exit(1)

# ── Step 5: API call ──────────────────────────────────────────
sep("Step 5 — API call (curl_cffi)")
try:
    from curl_cffi import requests as cffi_requests
    print("  ✓ curl_cffi available")
    session = cffi_requests.Session(impersonate="chrome124")
except ImportError:
    print("  ✗ curl_cffi not installed. Run: pip install curl_cffi")
    sys.exit(1)

org = cookies["lastActiveOrg"]
cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
headers = {
    "Cookie":           cookie_str,
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept":           "application/json",
    "Referer":          "https://claude.ai/",
    "sec-ch-ua-platform": '"Windows"',
}

try:
    r = session.get(f"https://claude.ai/api/organizations/{org}/usage", headers=headers, timeout=15)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  ✓ five_hour: {data.get('five_hour', '?')}")
        print(f"  ✓ seven_day: {data.get('seven_day', '?')}")
        print("\n  ✅ Everything working! The app should work correctly.")
    else:
        print(f"  ✗ Got {r.status_code} — response: {r.text[:200]}")
except Exception as e:
    print(f"  ✗ Request failed: {e}")
