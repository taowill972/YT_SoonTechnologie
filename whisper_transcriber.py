import time
from typing import List, Dict, Any
from faster_whisper import WhisperModel
from config import WHISPER_MODEL, MAX_BLOCK_DURATION, MIN_BLOCK_DURATION

_whisper_instance = None

def get_whisper_model() -> WhisperModel:
    global _whisper_instance
    if _whisper_instance is None:
        print(f"[Whisper] Initialisation du mod?le Faster-Whisper '{WHISPER_MODEL}' (CPU int8, 8 threads)...", flush=True)
        _whisper_instance = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=8)
        print("[Whisper] Mod?le Faster-Whisper op?rationnel.", flush=True)
    return _whisper_instance

def format_timestamp(seconds: float) -> str:
    s = int(round(seconds))
    hrs = s // 3600
    mins = (s % 3600) // 60
    secs = s % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"

def transcribe_audio_english(media_path: str) -> Dict[str, Any]:
    """
    Transcrit l'audio int?gralement mot pour mot avec timestamps pr?cis.
    Agr?ge les segments en blocs temporels ergonomiques (~20 ? 32s).
    """
    model = get_whisper_model()
    t0 = time.time()
    print(f"[Whisper] Transcription haute vitesse de : {media_path}...", flush=True)

    segments, info = model.transcribe(
        media_path,
        language="en",
        task="transcribe",
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=450),
        word_timestamps=False
    )

    seg_list = list(segments)
    elapsed = time.time() - t0
    dur = info.duration if info.duration > 0 else 1.0
    ratio = dur / elapsed if elapsed > 0 else 0
    print(f"[Whisper] ? {len(seg_list)} segments transcrits en {elapsed:.2f}s (Dur?e audio: {dur:.1f}s ? Vitesse: {ratio:.1f}x temps r?el)", flush=True)

    # Agr?gation en blocs temporels ?quilibr?s
    blocks: List[Dict[str, Any]] = []
    curr_texts: List[str] = []
    b_start = 0.0
    b_end = 0.0

    for s in seg_list:
        txt = s.text.strip()
        if not txt:
            continue
        if not curr_texts:
            b_start = s.start
        curr_texts.append(txt)
        b_end = s.end

        cur_dur = b_end - b_start
        if (cur_dur >= MAX_BLOCK_DURATION) or (cur_dur >= MIN_BLOCK_DURATION and txt.endswith(('.', '!', '?'))):
            blocks.append({
                "start": b_start,
                "end": b_end,
                "start_str": format_timestamp(b_start),
                "end_str": format_timestamp(b_end),
                "text_en": " ".join(curr_texts)
            })
            curr_texts = []

    if curr_texts:
        blocks.append({
            "start": b_start,
            "end": b_end,
            "start_str": format_timestamp(b_start),
            "end_str": format_timestamp(b_end),
            "text_en": " ".join(curr_texts)
        })

    return {
        "duration": dur,
        "elapsed": elapsed,
        "segments_count": len(seg_list),
        "blocks": blocks
    }

