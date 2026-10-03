import subprocess
from pathlib import Path
from typing import List, Dict, Any

from config import (
    REPO_DIR,
    CHANNEL_NAME,
    CHANNEL_URL,
    CHANNEL_HANDLE,
    MODEL_SIGNATURE
)

def update_readme_index(processed_videos: List[Dict[str, Any]], total_catalog_count: int = 33) -> None:
    readme_path = REPO_DIR / "README.md"
    pct = (len(processed_videos) / total_catalog_count * 100) if total_catalog_count > 0 else 0

    lines = [
        f"# ? YT_SoonTechnologie ? Veille & Transcriptions Multimodales",
        "",
        f"> Base de connaissances et transcriptions int?grales mot pour mot en fran?ais (audio via `gemini-3.8-flash` / `whisper-v3-large-turbo`) et descriptions visuelles d'?cran (via `gemini-3.5-flash-lite`) avec captures d'?cran cl?s et fiches interactives HTML de la cha?ne **[{CHANNEL_NAME}]({CHANNEL_URL})** ({CHANNEL_HANDLE}).",
        "",
        "## ?? Statistiques de l'Automatisation",
        f"- **Vid?os trait?es** : `{len(processed_videos)} / {total_catalog_count}` (`{pct:.1f}%`)",
        f"- **Mod?le Audio & Synth?se** : `gemini-3.8-flash` (avec Faster-Whisper large-v3-turbo, 100% Verbatim Fran?ais)",
        f"- **Mod?le Vision d'?cran** : `gemini-3.5-flash-lite` (Analyse d'?crans, interfaces & d?monstrations)",
        f"- **Signature de traitement** : `{MODEL_SIGNATURE}`",
        f"- **Mode Op?ratoire** : Z?ro coquille vide (Mode X - Sinc?rit? Technique Absolue)",
        "",
        "## ?? Index Exhaustif des Vid?os Analys?es",
        "",
        "| Date | R?f. Vid?o | Titre Fran?ais / Sujet | Fiche Markdown | Fiche Interactive HTML | Captures |",
        "| :--- | :--- | :--- | :--- | :--- | :---: |"
    ]

    for item in sorted(processed_videos, key=lambda x: x.get("upload_date", ""), reverse=True):
        date_str = item.get("upload_date", "N/A")
        if len(date_str) == 8:
            date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        else:
            date_formatted = date_str

        vid_id = item.get("id", "")
        title_fr = item.get("title_fr", item.get("title", ""))
        md_file = item.get("md_file", "")
        html_file = item.get("html_file", "")
        n_screens = item.get("screenshots_count", 0)

        yt_link = f"[{vid_id}](https://www.youtube.com/watch?v={vid_id})"
        md_link = f"[{Path(md_file).name}]({md_file})" if md_file else "-"
        html_link = f"[Voir Rapport HTML]({html_file})" if html_file else "-"

        lines.append(f"| {date_formatted} | {yt_link} | **{title_fr}** | {md_link} | {html_link} | `{n_screens}` |")

    lines.append("")
    lines.append("---")
    lines.append("*G?n?r? automatiquement par l'agent de veille multimodale Antigravity sur VPS Contabo.*")

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[GitManager] README.md mis ? jour ({len(processed_videos)} vid?os index?es).", flush=True)

def commit_and_push_repo(commit_msg: str) -> bool:
    try:
        subprocess.run(["git", "add", "."], cwd=REPO_DIR, check=True, capture_output=True)

        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_DIR, capture_output=True, text=True, check=True
        )
        if not status_res.stdout.strip():
            print("[GitManager] Aucun nouveau changement ? commiter.", flush=True)
            return True

        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=REPO_DIR, check=True, capture_output=True
        )
        print(f"[GitManager] Commit cr?? : '{commit_msg}'", flush=True)

        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_DIR, check=True, capture_output=True
        )
        print(f"[GitManager] ?? D?ploiement GitHub r?ussi vers origin/main.", flush=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[GitManager] Erreur Git (code {e.returncode}) : {e.stderr}", flush=True)
        return False
    except Exception as e:
        print(f"[GitManager] Erreur commit/push : {e}", flush=True)
        return False
