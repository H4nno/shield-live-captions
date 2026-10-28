"""Transcript + audio recording for the caption server.

Recording finals to SRT costs nothing (text bookkeeping); optional audio
recording writes the 16 kHz mono stream that already exists in memory.
"""
from __future__ import annotations

import logging
import os
import time
import wave

import numpy as np

log = logging.getLogger("shieldcc.record")


def _srt_ts(seconds: float) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class Recorder:
    def __init__(self, base_dir: str = None):
        env = os.environ.get("SHIELDCC_HOME", os.path.expanduser("~/shieldcc"))
        self.base_dir = base_dir or os.path.join(env, "recordings")
        self.active = False
        self.audio_active = False
        self._entries: list[tuple[float, float, str, str]] = []  # (start, end, text, original)
        self._wav_path = None
        self._wf = None
        self._t0 = 0.0
        self._last_end = 0.0

    # ---------- control ----------

    def start(self, with_audio: bool) -> dict:
        if self.active:
            return self.status()
        os.makedirs(self.base_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self._entries = []
        self._t0 = time.time()
        self._last_end = 0.0
        self.active = True
        self.audio_active = bool(with_audio)
        if with_audio:
            self._wav_path = os.path.join(self.base_dir, f"rec-{stamp}.wav")
            self._wf = wave.open(self._wav_path, "wb")
            self._wf.setnchannels(1)
            self._wf.setsampwidth(2)
            self._wf.setframerate(16000)
        else:
            self._wav_path = None
            self._wf = None
        log.info("recording started (audio=%s)", with_audio)
        return self.status()

    def stop(self) -> dict:
        if not self.active:
            return self.status()
        self.active = False
        self.audio_active = False
        if self._wf is not None:
            try:
                self._wf.close()
            except Exception:
                pass
            self._wf = None
        log.info("recording stopped: %d sentences", len(self._entries))
        return self.status()

    def status(self) -> dict:
        return {
            "active": self.active,
            "audio": self.audio_active,
            "sentences": len(self._entries),
            "wav": self._wav_path,
        }

    # ---------- data ----------

    def on_event(self, event: dict) -> None:
        if not self.active:
            return
        if event.get("type") == "final_amend" and self._entries:
            start, end, _t, _o = self._entries[-1]
            self._entries[-1] = (start, end, event.get("text", ""), event.get("original", ""))
            return
        if event.get("type") != "final":
            return
        t = float(event.get("t", time.time()))
        start = self._last_end if self._last_end > 0 else max(0.0, t - self._t0 - 4.0)
        end = max(start + 0.8, t - self._t0)
        self._entries.append((start, end, event.get("text", ""), event.get("original", "")))
        self._last_end = end

    def write_audio(self, chunk: np.ndarray) -> None:
        if self._wf is not None:
            try:
                pcm = np.clip(chunk, -1.0, 1.0)
                self._wf.writeframes((pcm * 32767.0).astype(np.int16).tobytes())
            except Exception:
                log.exception("audio write failed")

    def srt(self) -> str:
        out = []
        for i, (start, end, text, _original) in enumerate(self._entries, 1):
            out.append(f"{i}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{text}\n")
        return "\n".join(out)
