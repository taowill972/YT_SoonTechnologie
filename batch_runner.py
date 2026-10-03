import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, List

from config import (
    BASE_DIR,
    REPO_DIR,
    CATALOG_FILE,
    STATE_FILE,
    BATCH_SIZE
)
from pipeline import process_single_video
from git_manager import update_readme_index, commit_and_push_repo

def disable_cron_batch_job() -> bool:
    try:
        res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=True)
        lines = res.stdout.splitlines()
        new_lines = [l for l in lines if "yt_soontechnologie_batch" not in l and "YT_SoonTechnologie/run_cron.sh" not in l]
        if len(new_lines) != len(lines):
            new_cron = "\n".join(new_lines) + "\n"
            p = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            p.communicate(new_cron)
            print("[BatchRunner] ?? Crontab 6h retir? avec succ?s : routine d?sactiv?e suite ? la compl?tion int?grale.", flush=True)
            return True
        return False
    except Exception as e:
        print(f"[BatchRunner] Erreur lors de la d?sactivation du cron : {e}", flush=True)
        return False

def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "processed_ids": [],
        "processed_videos": [],
        "last_run_timestamp": None,
        "completed_count": 0,
        "total_catalog_count": 33,
        "status": "idle"
    }

def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def main():
    print(f"\n===================================================================", flush=True)
    print(f"?? [BatchRunner] Lancement de la routine 6h (Lot de {BATCH_SIZE} vid?os)", flush=True)
    print(f"?? Horodatage : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}", flush=True)
    print(f"===================================================================", flush=True)

    if not CATALOG_FILE.exists():
        print(f"[BatchRunner] ? Catalogue introuvable : {CATALOG_FILE}", flush=True)
        sys.exit(1)

    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        catalog_entries = json.load(f)

    total_catalog = len(catalog_entries)
    print(f"[BatchRunner] Catalogue global : {total_catalog} vid?os.", flush=True)

    state = load_state()
    state["total_catalog_count"] = total_catalog
    processed_ids_set = set(state.get("processed_ids", []))

    # Filtrer les vid?os non encore trait?es (d?j? class?es de la plus r?cente ? la plus ancienne)
    pending_videos = [v for v in catalog_entries if v.get("id") and v.get("id") not in processed_ids_set]
    print(f"[BatchRunner] Vid?os restantes ? transcrire : {len(pending_videos)} / {total_catalog}", flush=True)

    if len(pending_videos) == 0:
        print("\n?? [BatchRunner] TOUTES LES VID?OS DE LA CHA?NE ONT ?T? TRAIT?ES !", flush=True)
        print("?? Arr?t d?finitif de l'automatisation. Seule l'?coute continue des nouveaux flux est conserv?e.", flush=True)
        state["status"] = "ALL_VIDEOS_PROCESSED_AUTOMATION_COMPLETED"
        state["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_state(state)
        disable_cron_batch_job()
        sys.exit(0)

    # S?lectionner le lot de 7 vid?os
    current_batch = pending_videos[:BATCH_SIZE]
    print(f"[BatchRunner] D?marrage du lot de {len(current_batch)} vid?o(s) :", flush=True)
    for i, v in enumerate(current_batch):
        print(f"  [{i+1}/{len(current_batch)}] {v.get('id')} ? {v.get('title')} ({v.get('upload_date')})", flush=True)

    batch_success_count = 0
    for v in current_batch:
        vid_id = v.get("id")
        try:
            res = process_single_video(vid_id, catalog_title=v.get("title"))
            state["processed_ids"].append(vid_id)
            state["processed_videos"].append(res)
            state["completed_count"] = len(state["processed_ids"])
            save_state(state)

            update_readme_index(state["processed_videos"], total_catalog_count=total_catalog)
            commit_and_push_repo(f"feat: transcription multimodale {vid_id} - {res.get('title_fr')[:50]}")
            batch_success_count += 1
        except Exception as e:
            print(f"[BatchRunner] ? Erreur sur la vid?o {vid_id} : {e}", flush=True)

    state["last_run_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(state)

    print(f"\n===================================================================", flush=True)
    print(f"? [BatchRunner] Lot termin? : {batch_success_count}/{len(current_batch)} trait?e(s) avec succ?s.", flush=True)
    print(f"?? Total cumul? : {len(state['processed_ids'])} / {total_catalog} vid?os.", flush=True)
    print(f"===================================================================", flush=True)

    # Si ce lot a termin? la derni?re vid?o de la cha?ne
    if len(state["processed_ids"]) >= total_catalog:
        print("\n?? [BatchRunner] Derni?re vid?o atteinte ! D?sactivation de la routine crontab.", flush=True)
        state["status"] = "ALL_VIDEOS_PROCESSED_AUTOMATION_COMPLETED"
        save_state(state)
        disable_cron_batch_job()

if __name__ == "__main__":
    main()
