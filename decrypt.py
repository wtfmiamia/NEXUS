import sys
import os
import json
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()

def load_config():
    # Looks for config.json in the current folder or one level up
    for candidate in [
        os.path.join(BASE_PATH, 'config.json'),
        os.path.join(BASE_PATH, '..', 'config.json'),
    ]:
        try:
            with open(candidate, 'r') as f:
                return json.load(f)
        except Exception:
            continue
    return {}

def get_enc_key(config):
    token = config.get('nexusToken', '')
    if not token:
        print("[Error] nexusToken missing from config.json")
        sys.exit(1)
    return hashlib.sha256(token.encode()).digest()

def aes_decrypt(enc_key: bytes, iv_hex: str, tag_hex: str, data_hex: str) -> bytes:
    iv = bytes.fromhex(iv_hex)
    tag = bytes.fromhex(tag_hex)
    data = bytes.fromhex(data_hex)
    aesgcm = AESGCM(enc_key)
    return aesgcm.decrypt(iv, data + tag, None)

def read_db(config) -> list:
    db_path = os.path.join(BASE_PATH, 'db.json')
    if not os.path.exists(db_path):
        db_path = os.path.join(BASE_PATH, '..', 'db.json')
    if not os.path.exists(db_path):
        print(f"[Error] db.json not found near {BASE_PATH}")
        sys.exit(1)

    with open(db_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    # Fallback if the database root array is already unencrypted
    if isinstance(raw, list):
        return raw

    enc_key = get_enc_key(config)
    plain = aes_decrypt(enc_key, raw['iv'], raw['tag'], raw['data'])
    return json.loads(plain.decode('utf-8'))

def decrypt_password(stored_val, config) -> str:
    try:
        blob = json.loads(stored_val)
        enc_key = get_enc_key(config)
        plain = aes_decrypt(enc_key, blob['iv'], blob['tag'], blob['data'])
        return plain.decode('utf-8')
    except Exception:
        # If the password field isn't a valid JSON blob, assume it is plain text
        return stored_val

if __name__ == "__main__":
    config = load_config()
    
    if len(sys.argv) < 2:
        print("Usage: python decrypt.py <index_number>  (or 'all')")
        sys.exit(1)
        
    target = sys.argv[1]
    
    try:
        db = read_db(config)
        
        if target.lower() == 'all':
            print(f"\nFound {len(db)} total entries inside the database:")
            for index, account in enumerate(db):
                pwd = decrypt_password(account.get('password', ''), config)
                print(f"[{index}] User: {account.get('username')} | Pass: {pwd}")
        else:
            index = int(target)
            if index < 0 or index >= len(db):
                print(f"Index {index} out of bounds. The database contains {len(db)} accounts.")
                sys.exit(1)
                
            account = db[index]
            pwd = decrypt_password(account.get('password', ''), config)
            print("\n" + "="*40)
            print(f" Index:    {index}")
            print(f" Username: {account.get('username')}")
            print(f" Password: {pwd}")
            print("="*40 + "\n")
            
    except Exception as e:
        print(f"An error occurred while reading the database: {e}")