import sys
import os
import json
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ──────────────────────────────────────────────
#  PATH RESOLUTION & CONFIG
# ──────────────────────────────────────────────
def get_base_path():
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
    print("[Error] config.json not found.")
    return {}

CONFIG = load_config()

# ──────────────────────────────────────────────
#  DECRYPTION UTILITIES
# ──────────────────────────────────────────────
def get_enc_key():
    token = CONFIG.get('nexusToken', '')
    if not token:
        print("[CRITICAL] nexusToken missing from config.json")
        sys.exit(1)
    return hashlib.sha256(token.encode()).digest()

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
        print(f"[CRITICAL] db.json not found near {BASE_PATH}")
        sys.exit(1)

    with open(db_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    # Legacy fallback path if the DB file array isn't encrypted as a whole blob
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
        return f"[Failed to decrypt password: {e}]"

# ──────────────────────────────────────────────
#  MAIN EXECUTION
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test.py <index>")
        sys.exit(1)

    try:
        account_index = int(sys.argv[1])
    except ValueError:
        print(f"Error: Index must be an integer, got: {sys.argv[1]!r}")
        sys.exit(1)

    try:
        db = read_db()
        if account_index < 0 or account_index >= len(db):
            print(f"Error: Index {account_index} out of range. Database has {len(db)} entries.")
            sys.exit(1)

        account = db[account_index]
        username = account.get('username', 'N/A')
        raw_password_field = account.get('password', '')
        
        # Determine if the password field is a nested encrypted JSON string or plain text
        if raw_password_field.startswith('{'):
            decrypted_password = decrypt_password(raw_password_field)
        else:
            decrypted_password = raw_password_field

        print("\n" + "="*40)
        print(f" Account Index: {account_index}")
        print(f" Nickname:      {account.get('nickname', 'N/A')}")
        print("-"*40)
        print(f" Username:      {username}")
        print(f" Password:      {decrypted_password}")
        print("="*40 + "\n")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)