"""Turns incremental ASR text deltas into sentence-level events.

Splitting is deliberately lazy: a sentence is only cut once the stream has been
quiet for settle_s (the ASR often emits a sentence's last word one delta after
its punctuation — cutting immediately loses that word into the next sentence).
A leftover of up to two words after a split is merged back into the sentence
before it, and longer unpunctuated buffers are finalized after a speech pause.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Callable

# A sentence ends at . ! ? … followed by whitespace or end. Guard against very short
# fragments so abbreviations like "z.B." or numbers don't split prematurely.
_SENTENCE_RE = re.compile(r"^(.{12,}?[.!?…]+)(\s+|$)", re.DOTALL)

# Hard limit: if this many chars pile up without punctuation, flush anyway.
_MAX_BUFFER = 280


class Segmenter:
    def __init__(
        self,
        on_partial: Callable[[str, float], None],
        on_sentence: Callable[[str, float], None],
        gap_finalize_s: float = 1.8,
        settle_s: float = 0.5,
        max_sentence_len: int = 110,
    ):
        self.on_partial = on_partial
        self.on_sentence = on_sentence
        self.gap_finalize_s = gap_finalize_s
        self.settle_s = settle_s
        self.max_sentence_len = max_sentence_len
        self._buf = ""
        self._last_feed = time.time()
        self._lock = threading.Lock()

    def _split_long(self, sentences: list[str]) -> list[str]:
        """Break very long sentences into display-sized chunks at clause
        boundaries, so a talkative speaker can't fill the screen."""
        out: list[str] = []
        for s in sentences:
            while len(s) > self.max_sentence_len:
                cut = -1
                for sep in [", ", "; ", ". ", " – ", " - ", " "]:
                    idx = s.rfind(sep, 0, self.max_sentence_len)
                    if idx > 30:
                        cut = idx + len(sep.rstrip())
                        break
                if cut <= 0:
                    cut = self.max_sentence_len
                out.append(s[:cut].strip())
                s = s[cut:].lstrip()
            if s:
                out.append(s)
        return out

    # ---------- internals (lock held) ----------

    def _extract_locked(self) -> list[str]:
        """Split complete sentences off the buffer; merge a <=2-word tail into
        the last sentence so trailing words don't leak into the next one."""
        sentences: list[str] = []
        buf = self._buf
        while True:
            m = _SENTENCE_RE.match(buf)
            if not m:
                break
            s = m.group(1).strip()
            buf = buf[m.end():] if m.end(2) > m.end(1) else buf[len(m.group(0)):]
            if s:
                sentences.append(s)
        tail = buf.strip()
        if sentences and tail and len(tail.split()) <= 2:
            sentences[-1] = (sentences[-1] + " " + tail).strip()
            buf = ""
        self._buf = buf
        return self._split_long(sentences)

    # ---------- public API ----------

    def feed(self, delta: str) -> None:
        with self._lock:
            now = self._last_feed = time.time()
            self._buf = (self._buf + delta).replace("\n", " ")
            sentences = self._extract_locked() if len(self._buf) > _MAX_BUFFER else []
            partial = self._buf.strip()
        for s in sentences:
            self.on_sentence(s, now)
        self.on_partial(partial, now)

    def check_settle(self) -> None:
        """Called periodically: split sentences once the stream has been quiet."""
        with self._lock:
            if not self._buf or self.settle_s <= 0:
                return
            if time.time() - self._last_feed < self.settle_s:
                return
            now = time.time()
            sentences = self._extract_locked()
            partial = self._buf.strip()
        for s in sentences:
            self.on_sentence(s, now)
        if sentences or not partial:
            self.on_partial(partial, now)

    def check_gap(self) -> None:
        """Finalize the remaining buffer when the speaker has paused longer."""
        with self._lock:
            if self.gap_finalize_s <= 0:
                return
            text = self._buf.strip()
            if not text or len(text.split()) < 5:
                return
            if time.time() - self._last_feed < self.gap_finalize_s:
                return
            self._buf = ""
            now = time.time()
        for s in self._split_long([text]):
            self.on_sentence(s, now)
        self.on_partial("", now)

    def flush(self) -> None:
        with self._lock:
            sentence = self._buf.strip()
            self._buf = ""
        if sentence:
            for s in self._split_long([sentence]):
                self.on_sentence(s, time.time())
        self.on_partial("", time.time())
