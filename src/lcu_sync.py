

import sys
import json
import os
import asyncio

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ARG = sys.argv[1] if len(sys.argv) > 1 else None
TARGET_INDEX = None

if ARG and ARG != "IDENTIFY":
    try:
        TARGET_INDEX = int(ARG)
    except ValueError:
        print(f"[Error] Invalid index argument: {ARG!r}")
        sys.exit(1)


DB_PATH = os.path.join(os.getcwd(), 'db.json')


_TIER_BASE = {
    "IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
    "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400,
    "MASTER": 2800, "GRANDMASTER": 2800, "CHALLENGER": 2800,
}
_DIV_OFFSET = {"IV": 0, "III": 100, "II": 200, "I": 300}

def total_lp(tier: str, division: str, lp: int) -> int:
    return (
        _TIER_BASE.get(tier.upper(), 0)
        + _DIV_OFFSET.get(division.upper(), 0)
        + int(lp)
    )

async def get_ranked_history(connection, puuid: str, limit: int = 5) -> list:

    try:
        url = f'/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=30'
        res = await connection.request('get', url)
        if res.status != 200:
            print(f"[History] Non-200 response: {res.status}")
            return []

        data = await res.json()
        games = data.get('games', {}).get('games', [])

        history = []
        for game in games:
            if game.get('queueId') != 420:          # Solo/Duo only
                continue

            p_identities = game.get('participantIdentities', [])
            my_part_id = next(
                (pi['participantId'] for pi in p_identities
                 if pi.get('player', {}).get('puuid') == puuid),
                None
            )
            if my_part_id is None:
                continue

            my_stats = next(
                (p['stats'] for p in game.get('participants', [])
                 if p.get('participantId') == my_part_id),
                None
            )
            if my_stats is None:
                continue

            history.append("WIN" if my_stats.get('win') else "LOSS")
            if len(history) >= limit:
                break

        return history

    except Exception as e:
        print(f"[History Error] {e}")
        return []


def write_to_db(live_data: dict):
    if not os.path.exists(DB_PATH):
        print(f"[Error] db.json not found at: {DB_PATH}")
        return False

    if TARGET_INDEX is None:
        print("[Error] No target index — cannot write.")
        return False

    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            db = json.load(f)
    except Exception as e:
        print(f"[Error] Failed to read db.json: {e}")
        return False

    if not (0 <= TARGET_INDEX < len(db)):
        print(f"[Error] Index {TARGET_INDEX} out of range (db has {len(db)} entries)")
        return False

    acc = db[TARGET_INDEX]

    tier_str = live_data['tier']         
    lp_now   = live_data['lp']

    parts = tier_str.split()
    if len(parts) == 2:
        new_total = total_lp(parts[0], parts[1], lp_now)
    else:
        new_total = 0                      # UNRANKED → treat as 0

    session_start = acc.get('sessionStartLP', 0)
    if session_start == 0:
        session_start = new_total          # first sync this session

    lp_delta = new_total - session_start

    acc.update({
        "nickname":       live_data['displayName'],
        "riotId":         live_data['riotId'],
        "lastRank":       tier_str,
        "lp":             lp_now,
        "lpDelta":        lp_delta,
        "sessionStartLP": session_start,
        "wins":           live_data['wins'],
        "losses":         live_data['losses'],
        "history":        live_data['history'] if live_data['history'] else acc.get('history', []),
        "topChamp":       live_data['topChamp'],
        "topChampId":     live_data['topChampId'],
    })

    try:
        with open(DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        print(f"[Sync] Success — Index {TARGET_INDEX} | Rank: {tier_str} {lp_now}LP | Delta: {lp_delta:+d}")
        return True
    except Exception as e:
        print(f"[Error] Failed to write db.json: {e}")
        return False


def run_sync():
    """
    Connects to the LCU using the connector's internal loop logic.
    """
    from lcu_driver import Connector
    connector = Connector()

    @connector.ready
    async def on_ready(connection):
        try:
            if ARG == "IDENTIFY":
                res = await connection.request('get', '/lol-summoner/v1/current-summoner')
                if res.status == 200:
                    data = await res.json()
                    print(f"{data.get('gameName')}#{data.get('tagLine')}", flush=True)
                await connector.stop()
                return

            print(f"[Sync] LCU connected. Fetching data for index {TARGET_INDEX}...")

            res = await connection.request('get', '/lol-summoner/v1/current-summoner')
            if res.status != 200:
                print(f"[Error] Could not get summoner (HTTP {res.status}).")
                await connector.stop()
                return

            s_data = await res.json()
            puuid = s_data.get('puuid', '')

            ranked_res = await connection.request('get', f'/lol-ranked/v1/ranked-stats/{puuid}')
            r_data = await ranked_res.json()

            soloq = next((q for q in r_data.get('queues', []) if q.get('queueType') == 'RANKED_SOLO_5x5'), None)

            if soloq:
                tier_str = f"{soloq['tier']} {soloq['division']}"
                lp, wins, losses = soloq.get('leaguePoints', 0), soloq.get('wins', 0), soloq.get('losses', 0)
            else:
                tier_str, lp, wins, losses = "UNRANKED", 0, 0, 0

            mastery_res = await connection.request('get', '/lol-champion-mastery/v1/local-player/champion-mastery')
            m_data = await mastery_res.json()
            top_id, champ_alias = 0, "Square"

            if isinstance(m_data, list) and m_data:
                top_id = m_data[0].get('championId', 0)
                c_res  = await connection.request('get', f'/lol-game-data/assets/v1/champions/{top_id}.json')
                if c_res.status == 200:
                    c_json = await c_res.json()
                    champ_alias = c_json.get('alias', 'Square')

            history = await get_ranked_history(connection, puuid)
            write_to_db({
                "displayName": s_data.get('gameName', ''),
                "riotId":      f"{s_data.get('gameName','')}#{s_data.get('tagLine','')}",
                "tier":        tier_str, "lp": lp, "wins": wins, "losses": losses,
                "history":     history, "topChamp": champ_alias, "topChampId": top_id,
            })

        except Exception as e:
            print(f"[Sync Error] {e}")
        finally:
            await connector.stop()

    @connector.close
    async def disconnect(connection):
        print("[Sync] LCU Connection Closed.")

    # Start the connector (handles its own loop)
    connector.start()


if __name__ == "__main__":
    if not ARG:
        print("CRITICAL: Missing argument.")
        sys.exit(1)

    try:
        run_sync()
    except Exception as e:
        # Filter out normal exit signals
        if "KeyboardInterrupt" not in str(e):
            print(f"[Fatal] {e}")
        sys.exit(1)