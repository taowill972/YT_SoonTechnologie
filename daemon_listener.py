import os
import sys
import time
import json
import signal
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import (
    BASE_DIR,
    CATALOG_FILE,
    STATE_FILE,
    RSS_FEED_URL,
    CHANNEL_ID,
    CHANNEL_NAME,
    PROXY,
    PLAYER_CLIENT
)
from pipeline import process_single_video
from git_manager import update_readme_index, commit_and_push_repo

POLL_INTERVAL_SECONDS = 900  # 15 minutes entre chaque interrogation Atom RSS

running = True

def handle_signal(sig, frame):
    global running
    print(f"\n[Listener] Signal {sig} re?u, arr?t propre du d?mon d'?coute...", flush=True)
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_ids": [], "processed_videos": [], "known_baseline_ids": [], "completed_count": 0}

def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_rss_videos() -> List[Dict[str, str]]:
    req = urllib.request.Request(
        RSS_FEED_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"[Listener] Flux RSS ({e}), bascule sur fallback yt-dlp...", flush=True)
        return fetch_ytdlp_latest()

    videos = []
    try:
        root = ET.fromstring(xml_data)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015"
        }
        for entry in root.findall("atom:entry", ns):
            vid_id_elem = entry.find("yt:videoId", ns)
            title_elem = entry.find("atom:title", ns)
            pub_elem = entry.find("atom:published", ns)

            if vid_id_elem is not None and vid_id_elem.text:
                vid_id = vid_id_elem.text.strip()
                title = title_elem.text.strip() if title_elem is not None else ""
                published = pub_elem.text.strip() if pub_elem is not None else ""
                videos.append({
                    "id": vid_id,
                    "title": title,
                    "published": published
                })
    except Exception as e:
        print(f"[Listener] Erreur parsing XML Atom : {e}", flush=True)

    return videos

def fetch_ytdlp_latest() -> List[Dict[str, str]]:
    cmd = [
        "yt-dlp",
        "--proxy", PROXY,
        "--extractor-args", f"youtube:player_client={PLAYER_CLIENT}",
        "--flat-playlist",
        "--playlist-end", "5",
        "--dump-json",
        f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"
    ]
    videos = []
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in res.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            videos.append({
                "id": data.get("id"),
                "title": data.get("title", ""),
                "published": data.get("upload_date", "")
            })
    except Exception as e:
        print(f"[Listener] Erreur fallback yt-dlp : {e}", flush=True)

    return videos

def main():
    print(f"\n=======================================================", flush=True)
    print(f"?? [Listener] D?marrage de l'?coute Passive Z?ro-Token", flush=True)
    print(f"?? Cha?ne : {CHANNEL_NAME} ({CHANNEL_ID})", flush=True)
    print(f"?? Flux Atom XML : {RSS_FEED_URL}", flush=True)
    print(f"? Surveillance : 100% Z?RO TOKEN LLM consomm?s (HTTP Atom XML direct)", flush=True)
    print(f"?? Intervalle de scrutation : {POLL_INTERVAL_SECONDS}s ({POLL_INTERVAL_SECONDS//60} min)", flush=True)
    print(f"=======================================================", flush=True)

    while running:
        try:
            print(f"\n[Listener {time.strftime('%Y-%m-%d %H:%M:%S UTC')}] V?rification de nouvelles publications...", flush=True)
            latest_items = fetch_rss_videos()

            state = load_state()
            processed_ids = set(state.get("processed_ids", []))
            known_baseline = set(state.get("known_baseline_ids", []))

            # Une NOUVELLE publication est une vid?o qui n'?tait ni dans le catalogue initial, ni d?j? trait?e
            new_videos = [v for v in latest_items if v.get("id") and v.get("id") not in processed_ids and v.get("id") not in known_baseline]

            if not new_videos:
                print(f"[Listener] Aucune nouvelle publication d?tect?e. Veille active.", flush=True)
            else:
                print(f"[Listener] ?? NOUVELLE PUBLICATION D?TECT?E : {len(new_videos)} vid?o(s) !", flush=True)

                for nv in reversed(new_videos):
                    vid_id = nv["id"]
                    vid_title = nv.get("title", "")
                    print(f"\n[Listener] Traitement prioritaire de la nouvelle vid?o : {vid_id} ? '{vid_title}'", flush=True)

                    try:
                        res = process_single_video(vid_id, catalog_title=vid_title)
                        state["processed_ids"].append(vid_id)
                        state["processed_videos"].append(res)
                        state["completed_count"] = len(state["processed_ids"])
                        state["known_baseline_ids"].append(vid_id)
                        save_state(state)

                        update_readme_index(state["processed_videos"])
                        commit_and_push_repo(f"feat(listener): nouvelle vid?o {vid_id} - {res.get('title_fr', vid_title)[:50]}")
                        print(f"[Listener] ? Traitement et publication GitHub r?ussis pour {vid_id}.", flush=True)
                    except Exception as e:
                        print(f"[Listener] ? Erreur sur la nouvelle vid?o {vid_id} : {e}", flush=True)

        except Exception as e:
            print(f"[Listener] Erreur boucle d'?coute : {e}", flush=True)

        for _ in range(POLL_INTERVAL_SECONDS):
            if not running:
                break
            time.sleep(1)

    print("[Listener] Arr?t complet du d?mon d'?coute.", flush=True)

if __name__ == "__main__":
    main()
