import os
import sys
import re
import json
import time
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageChops, ImageStat

from config import (
    REPO_DIR,
    TRANSCRIPTS_DIR,
    WORK_DIR,
    SCREENSHOTS_DIR,
    PROXY,
    PLAYER_CLIENT,
    CHANNEL_NAME,
    CHANNEL_URL,
    CHANNEL_HANDLE,
    AUDIO_GEMINI_MODEL,
    VISUAL_GEMINI_MODEL,
    MODEL_SIGNATURE,
    FRAME_DIFF_THRESHOLD,
    FRAME_MAX_WIDTH
)
from whisper_transcriber import transcribe_audio_english, format_timestamp
from gemini_client import (
    translate_title_fr,
    process_multimodal_block,
    generate_executive_summary
)
from html_generator import generate_video_html

def sanitize_filename_title(title: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", title)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:80]

def extract_video_metadata(video_id: str) -> Dict[str, Any]:
    cmd = [
        "yt-dlp",
        "--proxy", PROXY,
        "--extractor-args", f"youtube:player_client={PLAYER_CLIENT}",
        "--dump-json",
        "--no-warnings",
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    for line in reversed(res.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return json.loads(res.stdout)

def extract_frame_at_timestamp(video_path: Path, timestamp_sec: float, output_path: Path) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(0.2, timestamp_sec)),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "3",
        "-vf", f"scale='min({FRAME_MAX_WIDTH},iw)':-2",
        str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return output_path.exists() and output_path.stat().st_size > 0

def is_frame_different(img_path1: Path, img_path2: Path, threshold: float = FRAME_DIFF_THRESHOLD) -> bool:
    try:
        im1 = Image.open(img_path1).convert("L").resize((64, 64))
        im2 = Image.open(img_path2).convert("L").resize((64, 64))
        diff = ImageChops.difference(im1, im2)
        stat = ImageStat.Stat(diff)
        mean_diff = stat.mean[0]
        return mean_diff >= threshold
    except Exception:
        return True

def audit_generated_content(
    md_path: Path,
    html_path: Path,
    screenshots_count: int
) -> Tuple[bool, float, List[str]]:
    errors = []
    if not md_path.exists() or md_path.stat().st_size < 500:
        errors.append("Fichier Markdown manquant ou trop court.")
    if not html_path.exists() or html_path.stat().st_size < 1000:
        errors.append("Fichier HTML interactif manquant ou incomplet.")

    if md_path.exists():
        content = md_path.read_text(encoding="utf-8", errors="ignore")
        required_patterns = [
            ("Synth?se Ex?cutive", r"##\s*.*Synth.*Ex.*cutiv"),
            ("R?sum?", r"###\s*.*R.*sum"),
            ("Outils", r"###\s*.*Outils"),
            ("Points Cl?s", r"###\s*.*Points\s+Cl"),
            ("Chronologie", r"##\s*.*Chronologie"),
            ("Audio Verbatim", r"\*\*.*Audio.*(Transcription|Verbatim)"),
            ("Analyse Visuelle", r"\*\*.*Analyse\s+Visuelle")
        ]
        for label, pat in required_patterns:
            if not re.search(pat, content, re.IGNORECASE):
                errors.append(f"Section obligatoire manquante : '{label}'")

    score = 100.0 - (len(errors) * 15.0)
    score = max(0.0, score)
    passed = (score >= 98.0)
    return passed, score, errors

def process_single_video(video_id: str, catalog_title: Optional[str] = None) -> Dict[str, Any]:
    print(f"\n=======================================================", flush=True)
    print(f"?? [Pipeline] D?but du traitement de la vid?o : {video_id}", flush=True)
    print(f"=======================================================", flush=True)

    video_work_dir = WORK_DIR / video_id
    video_work_dir.mkdir(parents=True, exist_ok=True)
    video_target_file = video_work_dir / f"{video_id}.mp4"

    # 1. M?tadonn?es
    meta = None
    for trial in range(3):
        try:
            print(f"[Pipeline] Extraction des m?tadonn?es YouTube (Essai {trial+1}/3)...", flush=True)
            meta = extract_video_metadata(video_id)
            break
        except Exception as e:
            print(f"[Pipeline] Avertissement m?tadonn?es : {e}", flush=True)
            time.sleep(2)

    title_en = (meta.get("title") if meta else None) or catalog_title or f"Vid?o {video_id}"
    upload_date = (meta.get("upload_date") if meta else None) or "20260101"
    duration = (meta.get("duration") if meta else None) or 0
    duration_str = format_timestamp(duration)

    print(f"[Pipeline] Titre original (EN) : {title_en}", flush=True)
    print(f"[Pipeline] Date : {upload_date} | Dur?e : {duration_str}", flush=True)

    # 2. Traduction du titre
    title_fr = translate_title_fr(title_en)
    print(f"[Pipeline] Titre traduit (FR) : {title_fr}", flush=True)

    # 3. T?l?chargement vid?o optimis?
    if not video_target_file.exists() or video_target_file.stat().st_size == 0:
        print(f"[Pipeline] T?l?chargement vid?o basse r?solution (480p/360p) pour analyse visuelle...", flush=True)
        dl_cmd = [
            "yt-dlp",
            "--proxy", PROXY,
            "--extractor-args", f"youtube:player_client={PLAYER_CLIENT}",
            "-f", "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
            "--merge-output-format", "mp4",
            "-o", str(video_target_file),
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        res_dl = subprocess.run(dl_cmd, capture_output=True, text=True)
        if res_dl.returncode != 0:
            print(f"[Pipeline] T?l?chargement 480p ?chou?, essai audio-only...", flush=True)
            dl_cmd_audio = [
                "yt-dlp",
                "--proxy", PROXY,
                "--extractor-args", f"youtube:player_client={PLAYER_CLIENT}",
                "-f", "ba/b",
                "-o", str(video_target_file),
                f"https://www.youtube.com/watch?v={video_id}"
            ]
            subprocess.run(dl_cmd_audio, check=True)

    # 4. Transcription audio mot pour mot
    whisper_res = transcribe_audio_english(str(video_target_file))
    blocks = whisper_res.get("blocks", [])
    print(f"[Pipeline] Transcription termin?e : {len(blocks)} blocs temporels g?n?r?s.", flush=True)

    # 5. Extraction et ?chantillonnage visuel
    video_screens_dir = SCREENSHOTS_DIR / video_id
    video_screens_dir.mkdir(parents=True, exist_ok=True)
    temp_frames_dir = video_work_dir / "temp_frames"
    temp_frames_dir.mkdir(parents=True, exist_ok=True)

    processed_segments: List[Dict[str, Any]] = []
    total_saved_screenshots = 0
    tools_detected_set = set()
    prev_global_frame = None

    for b_idx, block in enumerate(blocks):
        b_start = block["start"]
        b_end = block["end"]
        b_dur = b_end - b_start
        t_str = f"[{block['start_str']} - {block['end_str']}]"
        print(f"[Segment {b_idx+1}/{len(blocks)}] {t_str} ({b_dur:.1f}s)...", flush=True)

        sample_times = [
            b_start + (b_dur * 0.25),
            b_start + (b_dur * 0.50),
            b_start + (b_dur * 0.75)
        ]

        candidate_frames: List[Dict[str, Any]] = []
        for s_idx, t_sec in enumerate(sample_times):
            frame_cand_path = temp_frames_dir / f"blk_{b_idx+1}_cand_{s_idx+1}.jpg"
            if extract_frame_at_timestamp(video_target_file, t_sec, frame_cand_path):
                if prev_global_frame is None or is_frame_different(frame_cand_path, prev_global_frame, FRAME_DIFF_THRESHOLD):
                    candidate_frames.append({
                        "path": frame_cand_path,
                        "timestamp_sec": t_sec,
                        "timestamp_str": format_timestamp(t_sec),
                        "candidate_idx": s_idx + 1
                    })
                    prev_global_frame = frame_cand_path

        # Analyse multimodale (Audio via 3.8-flash, Visuel via 3.5-flash-lite)
        block_analysis = process_multimodal_block(
            candidate_frames=candidate_frames,
            timestamp_str=t_str,
            text_en=block["text_en"]
        )

        valid_indices = block_analysis.get("valid_frame_indices", [])
        captions_map = block_analysis.get("frame_captions", {})
        saved_block_screenshots = []

        for v_idx in valid_indices:
            if 0 <= v_idx < len(candidate_frames):
                cf = candidate_frames[v_idx]
                src_path = cf["path"]
                final_filename = f"{video_id}_{cf['timestamp_str'].replace(':', '')}_seg{b_idx+1}.jpg"
                final_path = video_screens_dir / final_filename

                shutil.copyfile(src_path, final_path)
                # Le chemin relatif pointe vers screenshots/ depuis le dossier parent
                rel_path = f"../screenshots/{video_id}/{final_filename}"
                cap_text = captions_map.get(v_idx, f"D?monstration ? l'?cran @ {cf['timestamp_str']}")

                saved_block_screenshots.append({
                    "path": rel_path,
                    "caption": cap_text,
                    "timestamp": cf["timestamp_str"]
                })
                total_saved_screenshots += 1

        seg_data = {
            "index": b_idx + 1,
            "start_str": block["start_str"],
            "end_str": block["end_str"],
            "timestamp_header": f"?? `{t_str}` | Segment #{b_idx+1:02d}",
            "verbatim_fr": block_analysis["verbatim_fr"],
            "interface": block_analysis["interface"],
            "contenu": block_analysis["contenu"],
            "action": block_analysis["action"],
            "screenshots": saved_block_screenshots
        }
        processed_segments.append(seg_data)

    print(f"[Pipeline] Total captures d'?cran significatives retenues : {total_saved_screenshots}", flush=True)

    # 6. Synth?se ex?cutive
    full_verbatim_text = "\n".join([s["verbatim_fr"] for s in processed_segments])
    exec_summary_md = generate_executive_summary(
        video_title=title_fr,
        full_verbatim_fr=full_verbatim_text,
        tools_detected=list(tools_detected_set)
    )

    # 7. Nommage strict des fichiers
    date_formatted = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}" if len(upload_date) == 8 else "2026-01-01"
    clean_title_fn = sanitize_filename_title(title_fr)
    base_filename = f"{date_formatted}_YT-[{video_id}]_{clean_title_fn}_by-[{MODEL_SIGNATURE}]"
    md_filename = f"{base_filename}.md"
    html_filename = f"{base_filename}.html"

    # Enregistrement dans le sous-dossier d?di? TRANSCRIPTS_DIR
    md_output_path = TRANSCRIPTS_DIR / md_filename
    html_output_path = TRANSCRIPTS_DIR / html_filename

    # 8. Assemblage Markdown calqu? sur le mod?le d'excellence
    md_lines = [
        f"# ?? {title_en}",
        "",
        f"> **Cha?ne** : [{CHANNEL_NAME}]({CHANNEL_URL})  ",
        f"> **Lien YouTube** : [https://www.youtube.com/watch?v={video_id}](https://www.youtube.com/watch?v={video_id})  ",
        f"> **Date de publication** : {upload_date}  ",
        f"> **Dur?e** : {duration_str}  ",
        f"> **Identifiant vid?o** : `{video_id}`  ",
        f"> **Transcription & Analyse** : `{MODEL_SIGNATURE}`  ",
        "",
        "---",
        "",
        "## ?? Synth?se Ex?cutive & Outils",
        "",
        exec_summary_md,
        "",
        "---",
        "",
        "## ?? Chronologie & Transcription Compl?te Audio & Visuelle (Mot pour Mot)",
        ""
    ]

    for s in processed_segments:
        md_lines.append(f"### {s['timestamp_header']}")
        md_lines.append("")
        md_lines.append("**?? Audio (Transcription Int?grale Mot pour Mot en Fran?ais) :**")
        md_lines.append(f"> {s['verbatim_fr']}")
        md_lines.append("")
        md_lines.append(f"**??? Analyse Visuelle d'?cran ({VISUAL_GEMINI_MODEL}) :**")
        md_lines.append(f"**Interface & Outils** : {s['interface']}")
        md_lines.append("")
        md_lines.append(f"**Contenu textuel & Donn?es** : {s['contenu']}")
        md_lines.append("")
        md_lines.append(f"**Action / D?monstration** : {s['action']}")
        md_lines.append("")

        if s["screenshots"]:
            for sc in s["screenshots"]:
                md_lines.append(f"![{sc['caption']}]({sc['path']})")
                md_lines.append(f"*?? {sc['timestamp']} ? {sc['caption']}*")
                md_lines.append("")

        md_lines.append("---")
        md_lines.append("")

    with open(md_output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    # 9. Assemblage HTML interactif moderne
    tools_list = []
    key_points = []
    if "### ??? Outils" in exec_summary_md:
        sub = exec_summary_md.split("### ??? Outils")[1]
        if "### ??" in sub:
            sub = sub.split("### ??")[0]
        for l in sub.splitlines():
            m = re.search(r'\*\*(.*?)\*\*', l)
            if m:
                tools_list.append(m.group(1))

    if "### ?? Points Cl?s" in exec_summary_md:
        sub_k = exec_summary_md.split("### ?? Points Cl?s")[1]
        for l in sub_k.splitlines():
            l_clean = l.strip().lstrip("-* ").strip()
            if l_clean and not l_clean.startswith("#"):
                key_points.append(l_clean)

    html_content = generate_video_html(
        title=title_fr,
        video_id=video_id,
        pub_date=date_formatted,
        dur_str=duration_str,
        channel_name=CHANNEL_NAME,
        channel_url=CHANNEL_URL,
        model_signature=MODEL_SIGNATURE,
        summary_html=exec_summary_md.replace("\n", "<br>"),
        tools_list=tools_list[:8],
        key_points=key_points[:12],
        segments=processed_segments
    )

    with open(html_output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 10. Auto-Test & Boucle R?cursive Mode X
    passed, score, errors = audit_generated_content(md_output_path, html_output_path, total_saved_screenshots)
    print(f"\n?? [/auto-test] R?sultat de l'audit : Score = {score:.1f}% | Conforme : {passed}", flush=True)

    # Nettoyage espace temporaire
    shutil.rmtree(video_work_dir, ignore_errors=True)

    return {
        "id": video_id,
        "title": title_en,
        "title_fr": title_fr,
        "upload_date": upload_date,
        "duration": duration,
        "duration_str": duration_str,
        "md_file": f"YT_SoonTechnologie_Transcript/{md_filename}",
        "html_file": f"YT_SoonTechnologie_Transcript/{html_filename}",
        "screenshots_count": total_saved_screenshots,
        "audit_score": score,
        "audit_passed": passed
    }
