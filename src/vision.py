import sys
import time
import pyautogui
import os
import subprocess
import json
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def log(msg):
    print(msg, flush=True)

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def get_base_path():
    """Works whether running as .py or compiled .exe"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()

def load_config():
    for candidate in [
        os.path.join(BASE_PATH, 'config.json'),
        os.path.join(BASE_PATH, '..', 'config.json'),
    ]:
        try:
            with open(candidate, 'r') as f:
                return json.load(f)
        except Exception:
            continue
    log("[Vision] Warning: config.json not found, using defaults.")
    return {}

CONFIG = load_config()
RIOT_CLIENT_PATH = CONFIG.get('riotClientPath', r"C:\Riot Games\Riot Client\RiotClientServices.exe")


_cfg_assets = CONFIG.get('assetsPath', '')
if _cfg_assets and os.path.isdir(_cfg_assets):
    ASSETS_DIR = _cfg_assets
elif os.path.isdir(os.path.join(BASE_PATH, '..', 'assets')):
    ASSETS_DIR = os.path.join(BASE_PATH, '..', 'assets')
else:
    ASSETS_DIR = os.path.join(BASE_PATH, 'assets')

log(f"[Vision] Base: {BASE_PATH} | Assets: {ASSETS_DIR}")

def get_enc_key():
    token = CONFIG.get('nexusToken', '')
    if not token:
        log("[Vision] CRITICAL: nexusToken missing from config.json")
        sys.exit(1)
    return hashlib.sha256(token.encode()).digest()   # 32 bytes, same as server.js

def _aes_decrypt(enc_key: bytes, iv_hex: str, tag_hex: str, data_hex: str) -> bytes:
    iv   = bytes.fromhex(iv_hex)
    tag  = bytes.fromhex(tag_hex)
    data = bytes.fromhex(data_hex)
    aesgcm = AESGCM(enc_key)
    return aesgcm.decrypt(iv, data + tag, None)

def read_db() -> list:
    db_path = os.path.join(BASE_PATH, 'db.json')
    if not os.path.exists(db_path):
        db_path = os.path.join(BASE_PATH, '..', 'db.json')
    if not os.path.exists(db_path):
        log(f"[Vision] CRITICAL: db.json not found near {BASE_PATH}")
        sys.exit(1)

    with open(db_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    if isinstance(raw, list):
        return raw

    enc_key = get_enc_key()
    plain   = _aes_decrypt(enc_key, raw['iv'], raw['tag'], raw['data'])
    return json.loads(plain.decode('utf-8'))

def decrypt_password(stored: str) -> str:
    try:
        blob    = json.loads(stored)
        enc_key = get_enc_key()
        plain   = _aes_decrypt(enc_key, blob['iv'], blob['tag'], blob['data'])
        return plain.decode('utf-8')
    except Exception as e:
        log(f"[Vision] WARNING: Could not decrypt password — {e}")
        return ''


def is_process_running(process_name):
    try:
        out = subprocess.check_output(
            f'tasklist /NH /FI "IMAGENAME eq {process_name}"',
            shell=True,
            stderr=subprocess.DEVNULL
        ).decode('utf-8', errors='ignore')
        return process_name.lower() in out.lower()
    except Exception:
        return False

def graceful_nuke():

    targets = [
        'LeagueClient.exe',
        'RiotClientServices.exe',
        'LeagueCrashHandler.exe',
        'RiotClientCrashHandler.exe',
    ]
    log("[Vision] Graceful nuke initiated...")

    for proc in targets:
        if is_process_running(proc):
            subprocess.run(
                f'taskkill /IM "{proc}"',
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

    time.sleep(1.5)

    still_alive = [p for p in targets if is_process_running(p)]
    for proc in still_alive:
        log(f"[Vision] Force-killing {proc}...")
        subprocess.run(
            f'taskkill /F /IM "{proc}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    if still_alive:
        time.sleep(1.0)

    log("[Vision] Nuke complete.")


def asset(name):
    return os.path.join(ASSETS_DIR, name)

def find_image(name, confidence=0.75, grayscale=True, region=None):
    """
    Returns a Box location if the image is found on screen, else None.
    Logs a warning if the asset file is missing entirely.
    """
    path = asset(name)
    if not os.path.exists(path):
        log(f"[Vision] WARNING: asset missing → {path}")
        return None
    try:
        kwargs = dict(confidence=confidence, grayscale=grayscale)
        if region:
            kwargs['region'] = region
        return pyautogui.locateOnScreen(path, **kwargs)
    except Exception:
        return None

def click_image(name, confidence=0.75, grayscale=True, region=None):
    """Find an image and click its centre. Returns True on success."""
    loc = find_image(name, confidence=confidence, grayscale=grayscale, region=region)
    if loc:
        x, y = pyautogui.center(loc)
        pyautogui.click(int(x), int(y))
        return True
    return False

def refocus_window():
    """Try to bring the Riot Client back to the foreground via its taskbar icon."""
    log("[Vision] Attempting refocus via taskbar icon...")
    sw, sh = pyautogui.size()
    region = (0, sh - 120, sw, 120)
    if click_image('riot_icon.png', confidence=0.88, grayscale=False, region=region):
        time.sleep(1.5)
        return True
    return False

def ensure_client_open(timeout=40):
    """
    Launch Riot Client if not running, then wait until the process appears.
    Uses a tight poll instead of fixed sleeps so it's as fast as the machine allows.
    """
    if is_process_running("RiotClientServices.exe"):
        log("[Vision] Riot Client already running.")
        return

    log("[Vision] Starting Riot Client...")
    subprocess.Popen(
        [RIOT_CLIENT_PATH,
         "--launch-product=league_of_legends",
         "--launch-patchline=live"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    deadline = time.time() + timeout
    while not is_process_running("RiotClientServices.exe"):
        if time.time() > deadline:
            log("CRITICAL: Riot Client failed to start within timeout.")
            sys.exit(1)
        time.sleep(1)

    log("[Vision] Riot Client process alive. Waiting for UI to render...")
    # Give the UI time to paint — poll for the username field instead of a fixed sleep
    for _ in range(20):
        time.sleep(1)
        if find_image('username.png', confidence=0.65) or find_image('username_active.png', confidence=0.65):
            log("[Vision] Login UI detected early — proceeding.")
            return
    # If we never found it, that's okay — perform_login will handle it

def perform_login(username, password, index):
    ensure_client_open()

    sw, sh = pyautogui.size()
    # Gentle centre-click to ensure the window has OS focus
    pyautogui.click(sw // 2, sh // 2)
    time.sleep(0.5)

    log(f"[Vision] Starting login sequence for: {username}")


    typed_credentials = False
    for attempt in range(25):
        if find_image('username_active.png', confidence=0.72):
            log(f"[Vision] Username field already active (attempt {attempt+1}). Typing directly.")
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            pyautogui.write(username, interval=0.04)
            pyautogui.press('tab')
            pyautogui.write(password, interval=0.04)
            time.sleep(0.4)
            pyautogui.press('enter')
            log("[Vision] Credentials submitted.")
            typed_credentials = True
            break

        if click_image('username.png', confidence=0.72):
            log(f"[Vision] Username field clicked (attempt {attempt+1}). Typing credentials.")
            time.sleep(0.3)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            pyautogui.write(username, interval=0.04)
            pyautogui.press('tab')
            pyautogui.write(password, interval=0.04)
            time.sleep(0.4)
            pyautogui.press('enter')
            log("[Vision] Credentials submitted.")
            typed_credentials = True
            break

        if attempt == 12:
            refocus_window()

        time.sleep(1)

    if not typed_credentials:
        log("[Vision] Username field not found — may already be on Play screen, continuing...")

    log("[Vision] Waiting for Play button...")
    # Give the login transition time to complete before starting the scan
    if typed_credentials:
        time.sleep(5)

    for attempt in range(20):
        if click_image('play_button.png', confidence=0.80):
            log("[Vision] Play button clicked. League launching.")
            print("V_SIGNAL:LOGIN_SUBMITTED", flush=True)
            log(f"[Vision] SUCCESS — sequence complete for index {index}")
            os._exit(0)

        if attempt == 10:
            refocus_window()

        time.sleep(1.5)

    log("[Vision] WARNING: Play button not found after timeout. Sending signal anyway.")
    print("V_SIGNAL:LOGIN_SUBMITTED", flush=True)
    os._exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        log("Usage: vision.exe <index>")
        sys.exit(1)

    try:
        account_index = int(sys.argv[1])
    except ValueError:
        log(f"CRITICAL: index must be a number, got: {sys.argv[1]!r}")
        sys.exit(1)

    try:
        db = read_db()
        if account_index < 0 or account_index >= len(db):
            log(f"CRITICAL: index {account_index} out of range (db has {len(db)} entries)")
            sys.exit(1)

        acc      = db[account_index]
        username = acc.get('username', '')
        password = decrypt_password(acc.get('password', ''))

        if not username:
            log(f"CRITICAL: account at index {account_index} has no username")
            sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        log(f"CRITICAL: Failed to read credentials from db — {e}")
        sys.exit(1)

    try:
        perform_login(username, password, account_index)
    except Exception as e:
        log(f"CRITICAL ERROR: {e}")
        sys.exit(1)
