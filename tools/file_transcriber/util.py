from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional


# -----------------------------
# 1) Utilities
# -----------------------------
def _to_dict(seg: Any) -> Dict[str, Any]:
    """SDKの TranscriptionDiarizedSegment / dict の両対応"""
    if isinstance(seg, dict):
        return seg
    # pydantic系
    if hasattr(seg, "model_dump"):
        return seg.model_dump()
    # openai-python の一部は to_dict を持つ
    if hasattr(seg, "to_dict"):
        return seg.to_dict()
    # 最終手段
    return {
        "id": getattr(seg, "id", None),
        "start": getattr(seg, "start", None),
        "end": getattr(seg, "end", None),
        "speaker": getattr(seg, "speaker", None),
        "text": getattr(seg, "text", None),
        "type": getattr(seg, "type", None),
    }


def _sec_to_srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _sec_to_mmss(t: float) -> str:
    ms = int(round(t * 1000))
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{m:02d}:{s:02d}.{ms:03d}"


def _normalize_whitespace_ja(text: str) -> str:
    # 日本語の不自然な空白をある程度除去
    # ただし英単語周りは潰しすぎない
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([、。！？])", r"\1", text)
    text = re.sub(r"([、。！？])\s+", r"\1", text)
    return text.strip()


def _is_tiny(seg: Dict[str, Any], *, max_chars: int = 2, max_dur: float = 0.35) -> bool:
    txt = (seg.get("text") or "").strip()
    dur = (seg.get("end") or 0) - (seg.get("start") or 0)
    return (len(txt) <= max_chars) or (dur <= max_dur)


# -----------------------------
# 2) Core post-processing
# -----------------------------
def normalize_segments(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    segs_raw = resp.get("segments") or []
    segs = [_to_dict(s) for s in segs_raw]
    # sort
    segs.sort(key=lambda x: (x.get("start", 0) or 0, x.get("end", 0) or 0))
    # clean text
    for s in segs:
        s["text"] = _normalize_whitespace_ja(str(s.get("text") or ""))
    return segs


def absorb_tiny_segments(
    segs: List[Dict[str, Any]],
    *,
    max_chars: int = 2,
    max_dur: float = 0.35,
) -> List[Dict[str, Any]]:
    """
    "Hmm" や "路" のような極小断片を前後に吸収して読みにくさを減らす。
    ルール:
      - tiny かつ前が同一話者なら前に結合
      - そうでなければ後ろが同一話者なら後ろに前置
      - どちらも無理ならそのまま残す
    """
    if not segs:
        return segs

    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(segs):
        cur = segs[i]
        if _is_tiny(cur, max_chars=max_chars, max_dur=max_dur):
            prev = out[-1] if out else None
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            txt = (cur.get("text") or "").strip()

            if prev and prev.get("speaker") == cur.get("speaker"):
                prev["text"] = (prev.get("text", "") + " " + txt).strip()
                prev["end"] = max(prev.get("end", 0) or 0, cur.get("end", 0) or 0)
                i += 1
                continue

            if nxt and nxt.get("speaker") == cur.get("speaker"):
                nxt["text"] = (txt + " " + (nxt.get("text") or "")).strip()
                nxt["start"] = min(nxt.get("start", 0) or 0, cur.get("start", 0) or 0)
                i += 1
                continue

        out.append(cur)
        i += 1
    return out


def merge_consecutive(
    segs: List[Dict[str, Any]],
    *,
    max_gap: float = 0.8,
) -> List[Dict[str, Any]]:
    """
    同一話者の連続セグメントをマージ（Bが細切れ問題の解消）。
    max_gap: セグメント間の無音/間の許容秒数
    """
    if not segs:
        return segs

    merged = [segs[0].copy()]
    for s in segs[1:]:
        last = merged[-1]
        same_speaker = (last.get("speaker") == s.get("speaker"))
        gap = (s.get("start") or 0) - (last.get("end") or 0)

        if same_speaker and gap <= max_gap:
            last["text"] = (last.get("text", "") + " " + (s.get("text") or "")).strip()
            last["end"] = max(last.get("end", 0) or 0, s.get("end", 0) or 0)
        else:
            merged.append(s.copy())
    return merged

# -----------------------------
# 3) Renderers
# -----------------------------
def render_dialogue(
    segs: List[Dict[str, Any]],
    speaker_names: Optional[Dict[str, str]] = None,
    show_time: bool = True,
) -> str:
    """
    会話形式の表示（読み物）
    """
    speaker_names = speaker_names or {}
    lines: List[str] = []
    for s in segs:
        sp = s.get("speaker") or "?"
        name = speaker_names.get(sp, f"Speaker {sp}")
        t = f"[{_sec_to_mmss(float(s.get('start') or 0))}–{_sec_to_mmss(float(s.get('end') or 0))}] " if show_time else ""
        lines.append(f"{t}{name}: {s.get('text','')}")
    return "\n\n".join(lines)


def render_timeline(segs: List[Dict[str, Any]]) -> str:
    """
    デバッグ向けのタイムライン表示
    """
    lines = []
    for s in segs:
        lines.append(
            f"{_sec_to_mmss(float(s.get('start') or 0))} - {_sec_to_mmss(float(s.get('end') or 0))} "
            f"{s.get('speaker','?')}: {s.get('text','')}"
        )
    return "\n".join(lines)


def render_srt(
    segs: List[Dict[str, Any]],
    speaker_names: Optional[Dict[str, str]] = None,
    max_line_chars: int = 28,
) -> str:
    """
    SRT出力（字幕）: Speaker名を先頭に付与
    """
    speaker_names = speaker_names or {}

    def wrap(text: str) -> str:
        # 単純な文字数折り返し（日本語向け）
        text = text.strip()
        if len(text) <= max_line_chars:
            return text
        out = []
        while text:
            out.append(text[:max_line_chars])
            text = text[max_line_chars:]
        return "\n".join(out)

    blocks = []
    for i, s in enumerate(segs, 1):
        sp = s.get("speaker") or "?"
        name = speaker_names.get(sp, f"Speaker {sp}")
        start = _sec_to_srt_time(float(s.get("start") or 0))
        end = _sec_to_srt_time(float(s.get("end") or 0))
        body = wrap(f"{name}: {s.get('text','')}")
        blocks.append(f"{i}\n{start} --> {end}\n{body}\n")
    return "\n".join(blocks)


# -----------------------------
# 4) One-shot pipeline
# -----------------------------
def pretty_diarized_output(
    diarized_resp: Dict[str, Any],
    *,
    speaker_names: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    segs = normalize_segments(diarized_resp)
    segs = absorb_tiny_segments(segs, max_chars=2, max_dur=0.35)
    segs = merge_consecutive(segs, max_gap=0.8)

    return {
        "dialogue": render_dialogue(segs, speaker_names=speaker_names, show_time=True),
        "timeline": render_timeline(segs),
        "srt": render_srt(segs, speaker_names=speaker_names, max_line_chars=28),
    }
