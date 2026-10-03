import os
import sys
import re
import json
import base64
import time
import socket
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import (
    AUDIO_KEYS_FILE,
    VISUAL_KEYS_FILE,
    AUDIO_GEMINI_MODEL,
    AUDIO_FALLBACK_MODELS,
    VISUAL_GEMINI_MODEL,
    VISUAL_FALLBACK_MODELS,
    CHANNEL_NAME
)

socket.setdefaulttimeout(45)

def _load_keys(filepath: Path) -> List[str]:
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            keys = [k.strip() for k in f if k.strip() and not k.startswith("#")]
        if keys:
            return keys
    raise ValueError(f"Fichier de cl?s introuvable ou vide : {filepath}")

_AUDIO_KEYS = _load_keys(AUDIO_KEYS_FILE)
_VISUAL_KEYS = _load_keys(VISUAL_KEYS_FILE)

_AUDIO_IDX = [0]
_VISUAL_IDX = [0]

STATS = {"audio_calls": 0, "visual_calls": 0, "rotations": 0, "failures": 0}

def call_gemini_audio(parts: List[Dict[str, Any]], retries: int = 4) -> str:
    """Appel pour la transcription/synth?se audio avec gemini-3.8-flash et repli r?silient."""
    models_to_try = [AUDIO_GEMINI_MODEL] + AUDIO_FALLBACK_MODELS
    
    for model in models_to_try:
        for attempt in range(retries):
            key = _AUDIO_KEYS[_AUDIO_IDX[0] % len(_AUDIO_KEYS)]
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            
            try:
                with urllib.request.urlopen(req, timeout=35) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    cands = data.get("candidates", [])
                    if cands and "content" in cands[0] and "parts" in cands[0]["content"]:
                        STATS["audio_calls"] += 1
                        return cands[0]["content"]["parts"][0].get("text", "")
            except urllib.error.HTTPError as e:
                _AUDIO_IDX[0] += 1
                STATS["rotations"] += 1
                if e.code in (429, 503, 500):
                    time.sleep(1.5)
                    continue
                err_text = e.read().decode("utf-8", "ignore")[:150]
                print(f"[Gemini-Audio] HTTPError {e.code} sur {model}: {err_text}", flush=True)
            except Exception as e:
                _AUDIO_IDX[0] += 1
                time.sleep(1.5)
                
    STATS["failures"] += 1
    return ""

def call_gemini_visual(parts: List[Dict[str, Any]], retries: int = 4) -> str:
    """Appel pour l'analyse visuelle multimodale avec gemini-3.5-flash-lite et repli r?silient."""
    models_to_try = [VISUAL_GEMINI_MODEL] + VISUAL_FALLBACK_MODELS
    
    for model in models_to_try:
        for attempt in range(retries):
            key = _VISUAL_KEYS[_VISUAL_IDX[0] % len(_VISUAL_KEYS)]
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    cands = data.get("candidates", [])
                    if cands and "content" in cands[0] and "parts" in cands[0]["content"]:
                        STATS["visual_calls"] += 1
                        return cands[0]["content"]["parts"][0].get("text", "")
            except urllib.error.HTTPError as e:
                _VISUAL_IDX[0] += 1
                STATS["rotations"] += 1
                if e.code in (429, 503, 500):
                    time.sleep(1.0)
                    continue
                err_text = e.read().decode("utf-8", "ignore")[:150]
                print(f"[Gemini-Visual] HTTPError {e.code} sur {model}: {err_text}", flush=True)
            except Exception as e:
                _VISUAL_IDX[0] += 1
                time.sleep(1.0)
                
    STATS["failures"] += 1
    return ""

def translate_title_fr(title_en: str) -> str:
    prompt = (
        "Tu es un traducteur expert en journalisme tech, IA et documentaires num?riques.\n"
        "Traduis ce titre de vid?o YouTube de l'anglais vers un fran?ais captivant, ?l?gant et fid?le.\n"
        "Garde les noms de marques, protocoles et personnes intacts (Elon, Anthropic, Kalshi, Sora, OpenAI, etc.).\n"
        "R?ponds STRICTEMENT avec le titre traduit uniquement, sans guillemets ni fioritures.\n\n"
        f"Titre : {title_en}"
    )
    res = call_gemini_audio([{"text": prompt}])
    return res.strip().replace('"', '') if res else title_en

def process_multimodal_block(
    candidate_frames: List[Dict[str, Any]],
    timestamp_str: str,
    text_en: str
) -> Dict[str, Any]:
    default_res = {
        "verbatim_fr": text_en,
        "valid_frame_indices": [],
        "frame_captions": {},
        "interface": "Pr?sentation ou reportage sans interface informatique partag?e.",
        "contenu": "Explications orales des faits et investigations.",
        "action": "Narration documentaire et mise en contexte du sujet."
    }

    # 1. Traduction mot ? mot int?grale de l'audio en fran?ais via Gemini 3.8 Flash (Audio model)
    audio_prompt = (
        f"Tu es un traducteur et transcripteur professionnel pour la cha?ne documentaire {CHANNEL_NAME} (segment {timestamp_str}).\n"
        f"Voici le discours audio anglais exact prononc? dans ce segment :\n"
        f'"""\n{text_en}\n"""\n\n'
        "Traduis ce discours mot ? mot int?gralement en fran?ais, naturel et sans AUCUNE coupure ni r?sum?.\n"
        "Si c'est musical ou sans parole, indique : [S?quence sonore / Ambiance musicale].\n"
        "R?ponds uniquement avec le texte fran?ais complet."
    )
    verbatim_fr = call_gemini_audio([{"text": audio_prompt}])
    if verbatim_fr and verbatim_fr.strip():
        default_res["verbatim_fr"] = verbatim_fr.strip()

    # 2. Analyse visuelle multimodale via Gemini 3.5 Flash-Lite (Visual model)
    n_imgs = len(candidate_frames)
    if n_imgs == 0:
        return default_res

    img_list_txt = "\n".join([f"- Image #{i+1} : horodatage @ {cf.get('timestamp_str', '')}" for i, cf in enumerate(candidate_frames)])
    visual_prompt = (
        f"Tu es un analyste visuel pour la cha?ne {CHANNEL_NAME} (segment {timestamp_str}).\n"
        f"Contexte audio du segment : {default_res['verbatim_fr'][:300]}\n\n"
        f"Tu as re?u {n_imgs} capture(s) d'?cran candidate(s) :\n{img_list_txt}\n\n"
        "DIRECTIVE DE S?LECTION D'IMAGES :\n"
        "- Retiens les images de d?monstrations r?elles : ?crans d'ordinateurs, logiciels, sites web, interfaces de bots/IA, graphiques, s?quences d'enqu?te terrain significatives, mat?riel robotique, etc.\n"
        "- ?limine les images purement floues ou les gros plans statiques du pr?sentateur qui parle sans aucun ?l?ment graphique pertinent.\n\n"
        "Format STRICT obligatoire de ta r?ponse :\n"
        "[VALID_IMAGES] <num?ros s?par?s par virgule (ex: 1, 2) ou AUCUNE>\n"
    )
    for i in range(n_imgs):
        visual_prompt += f"[DESC_IMAGE_{i+1}] <l?gende concise d?crivant pr?cis?ment ce qui est visible ? l'?cran>\n"
    visual_prompt += (
        "[INTERFACE] <logiciels, sites ou environnements montr?s>\n"
        "[CONTENU] <donn?es, textes ou visuels affich?s ? l'?cran>\n"
        "[ACTION] <action, exp?rience ou manipulation effectu?e>"
    )

    visual_parts: List[Dict[str, Any]] = [{"text": visual_prompt}]
    for cf in candidate_frames:
        img_path = cf.get("path")
        if img_path and isinstance(img_path, Path) and img_path.exists() and img_path.stat().st_size > 0:
            try:
                with open(img_path, "rb") as f:
                    b64_img = base64.b64encode(f.read()).decode("utf-8")
                visual_parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64_img
                    }
                })
            except Exception:
                pass

    raw_vis = call_gemini_visual(visual_parts)
    if not raw_vis:
        return default_res

    res = dict(default_res)
    try:
        valid_indices = []
        frame_captions = {}
        if "[VALID_IMAGES]" in raw_vis:
            raw_val = raw_vis.split("[VALID_IMAGES]")[1]
            for m in ["[DESC_IMAGE_", "[INTERFACE]", "[CONTENU]", "[ACTION]"]:
                if m in raw_val:
                    raw_val = raw_val.split(m)[0]
            raw_val = raw_val.strip().upper()

            if "AUCUNE" not in raw_val and "NONE" not in raw_val and "ZERO" not in raw_val:
                if "TOUTES" in raw_val or "TOUT" in raw_val or "ALL" in raw_val:
                    valid_indices = list(range(n_imgs))
                else:
                    for token in re.findall(r'\b\d+\b', raw_val):
                        num = int(token)
                        if 1 <= num <= n_imgs:
                            valid_indices.append(num - 1)

        for i in range(n_imgs):
            tag = f"[DESC_IMAGE_{i+1}]"
            if tag in raw_vis:
                part_desc = raw_vis.split(tag)[1]
                for next_tag in [f"[DESC_IMAGE_{j+1}]" for j in range(i+1, n_imgs)] + ["[INTERFACE]", "[CONTENU]", "[ACTION]"]:
                    if next_tag in part_desc:
                        part_desc = part_desc.split(next_tag)[0]
                desc_text = part_desc.strip().lstrip(": -").strip()
                if desc_text and not desc_text.startswith("<"):
                    frame_captions[i] = desc_text

        res["valid_frame_indices"] = sorted(list(set(valid_indices)))
        res["frame_captions"] = frame_captions

        if "[INTERFACE]" in raw_vis:
            p_i = raw_vis.split("[INTERFACE]")[1]
            for m in ["[CONTENU]", "[ACTION]"]:
                if m in p_i:
                    p_i = p_i.split(m)[0]
            res["interface"] = p_i.strip()

        if "[CONTENU]" in raw_vis:
            p_c = raw_vis.split("[CONTENU]")[1]
            if "[ACTION]" in p_c:
                p_c = p_c.split("[ACTION]")[0]
            res["contenu"] = p_c.strip()

        if "[ACTION]" in raw_vis:
            res["action"] = raw_vis.split("[ACTION]")[1].strip()

    except Exception as e:
        print(f"[Gemini-Visual] Erreur parsing bloc visuel : {e}", flush=True)

    return res

def generate_executive_summary(video_title: str, full_verbatim_fr: str, tools_detected: List[str]) -> str:
    tools_str = ", ".join(tools_detected) if tools_detected else "Intelligence Artificielle, Robotique, Bot Farms, Technologies ?mergentes"
    prompt = (
        f"Tu es un analyste expert des technologies d'avant-garde et journaliste tech d'investigation.\n"
        f"Vid?o de la cha?ne {CHANNEL_NAME} intitul?e : ? {video_title} ?.\n"
        f"Technologies & sujets cl?s : {tools_str}\n\n"
        f"Transcription int?grale de la vid?o en fran?ais :\n\"\"\"\n{full_verbatim_fr[:10000]}\n\"\"\"\n\n"
        "R?dige une synth?se ex?cutive structur?e, dense, fluide et tr?s riche en enseignements concrets en fran?ais.\n"
        "Tu DOIS STRICTEMENT employer ces titres de niveau 3 exacts :\n"
        "### ?? R?sum?\n"
        "(2 ? 3 paragraphes immersifs et pr?cis expliquant le c?ur de l'enqu?te/exp?rience, les rouages techniques d?voil?s et l'impact direct sur l'?cosyst?me tech)\n\n"
        "### ??? Outils, Mod?les & Logiciels Pr?sent?s\n"
        "(Liste ? puces exhaustive avec nom de l'outil/technologie en gras et une phrase explicative percutante)\n\n"
        "### ?? Points Cl?s & Enseignements Strat?giques\n"
        "(8 ? 12 points cl?s d?taill?s, analytiques et actionnables r?sumant les d?couvertes, les chiffres marquants, les protocoles et les implications futures)"
    )

    res = call_gemini_audio([{"text": prompt}])
    if not res:
        res = (
            "### ?? R?sum?\n"
            f"Dans ce reportage immersif intitul? **{video_title}**, la cha?ne Soon explore en d?tail les coulisses techniques et soci?tales des nouvelles technologies.\n\n"
            "### ??? Outils, Mod?les & Logiciels Pr?sent?s\n"
            "- **Technologies IA et Automatisation** : D?ploiement d'agents et scripts connect?s.\n\n"
            "### ?? Points Cl?s & Enseignements Strat?giques\n"
            "- Comprendre les architectures distribu?es et leur impact sur le web moderne.\n"
            "- Mesurer les implications ?thiques et ?conomiques des technologies autonomes."
        )
    return res
