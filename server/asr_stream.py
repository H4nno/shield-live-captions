"""Streaming ASR wrapper for nvidia/nemotron-3.5-asr-streaming-0.6b (transformers >= 5.13).

Audio (16 kHz mono float32 numpy) is pushed via feed_audio(); text deltas are emitted
through the on_delta callback as they are decoded. The generate() thread pulls mel
chunks from a generator that blocks until enough audio has arrived, following the
chunking scheme from the model card.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

log = logging.getLogger("shieldcc.asr")

MODEL_ID = "nvidia/nemotron-3.5-asr-streaming-0.6b"


class StreamingAsr:
    def __init__(
        self,
        on_delta: Callable[[str], None],
        model_id: str = MODEL_ID,
        language: str = "de-DE",
        lookahead_tokens: int = 6,
        device: str = "cuda",
    ):
        self.on_delta = on_delta
        self.model_id = model_id
        self.language = language
        self.lookahead_tokens = lookahead_tokens
        self.device = device

        self._cv = threading.Condition()
        self._buf = np.empty(0, dtype=np.float32)
        self._base = 0            # absolute sample index of self._buf[0]
        self._eos = False
        self._started = False
        self._threads: list[threading.Thread] = []

        self._load()

    # ---------- model ----------

    def _load(self):
        from transformers import AutoModelForRNNT, AutoProcessor

        log.info("loading %s (lookahead=%d, lang=%s)", self.model_id, self.lookahead_tokens, self.language)
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.processor.set_num_lookahead_tokens(self.lookahead_tokens)
        self.model = AutoModelForRNNT.from_pretrained(self.model_id).to(self.device)
        self.model.eval()
        self.sampling_rate = self.processor.feature_extractor.sampling_rate
        log.info("model ready, sampling_rate=%s", self.sampling_rate)

    # ---------- audio input ----------

    def feed_audio(self, chunk: np.ndarray):
        """chunk: float32 mono at self.sampling_rate (16 kHz)."""
        if chunk.size == 0:
            return
        with self._cv:
            self._buf = np.concatenate((self._buf, np.asarray(chunk, dtype=np.float32)))
            self._cv.notify_all()
            if not self._started:
                self._started = True
                self._start_threads()

    def finish(self, pad_seconds: float = 2.0):
        """Signal end of audio; pads with silence so the tail decodes, then ends generate()."""
        with self._cv:
            if not self._eos:
                self._buf = np.concatenate(
                    (self._buf, np.zeros(int(pad_seconds * self.sampling_rate), dtype=np.float32))
                )
            self._eos = True
            self._cv.notify_all()
            if not self._started:
                self._started = True
                self._start_threads()

    def wait_done(self):
        for t in self._threads:
            t.join()

    # ---------- streaming machinery ----------

    def _wait_for(self, absolute_end: int) -> bool:
        """Block until buffer covers absolute_end. Returns False on EOS with no more data."""
        with self._cv:
            while self._base + self._buf.size < absolute_end and not self._eos:
                self._cv.wait()
            return self._base + self._buf.size >= absolute_end

    def _slice(self, start: int, end: int):
        self._wait_for(end)
        with self._cv:
            if self._base + self._buf.size < end:
                return None
            return self._buf[start - self._base : end - self._base].copy()

    def _trim_to(self, absolute_start: int):
        with self._cv:
            drop = absolute_start - self._base
            if drop > 0:
                self._buf = self._buf[drop:]
                self._base = absolute_start

    def _process(self, audio: np.ndarray, is_first: bool):
        import torch

        inputs = self.processor(
            audio,
            sampling_rate=self.sampling_rate,
            is_streaming=True,
            is_first_audio_chunk=is_first,
            language=self.language,
            return_tensors="pt",
        )
        return inputs

    def _features(self):
        """Generator yielding input_features tensors, mirroring the model-card streaming example."""
        import torch

        p = self.processor
        fe = p.feature_extractor
        hop = fe.hop_length
        n_fft = fe.n_fft

        first = self._slice(0, p.num_samples_first_audio_chunk)
        if first is None:
            first = np.zeros(p.num_samples_first_audio_chunk, dtype=np.float32)
        first_inputs = self._process(first, is_first=True)
        first_feats = first_inputs.input_features[:, : p.num_mel_frames_first_audio_chunk, :]
        first_feats = first_feats.to(self.device, dtype=self.model.dtype)

        def chained():
            yield first_feats
            mel_frame_idx = p.num_mel_frames_first_audio_chunk
            while True:
                start_idx = max(mel_frame_idx * hop - n_fft // 2, 0)
                end_idx = start_idx + p.num_samples_per_audio_chunk
                chunk = self._slice(start_idx, end_idx)
                self._trim_to(start_idx)
                if chunk is None:
                    return
                inputs = self._process(chunk, is_first=False)
                yield inputs.input_features.to(self.device, dtype=self.model.dtype)
                mel_frame_idx += p.num_mel_frames_per_audio_chunk

        return first_inputs, chained()

    def _start_threads(self):
        from transformers import TextIteratorStreamer

        streamer = TextIteratorStreamer(self.processor.tokenizer, skip_special_tokens=True)

        def gen():
            import torch

            try:
                first_inputs, feats = self._features()
                gen_kwargs = {k: v for k, v in first_inputs.items() if k != "input_features"}
                gen_kwargs["input_features"] = feats
                gen_kwargs["streamer"] = streamer
                with torch.no_grad():
                    self.model.generate(**gen_kwargs)
            except Exception:
                log.exception("generate() failed")

        def reader():
            try:
                for text_chunk in streamer:
                    if text_chunk:
                        self.on_delta(text_chunk)
            except Exception:
                log.exception("streamer reader failed")

        t1 = threading.Thread(target=gen, name="asr-generate", daemon=True)
        t2 = threading.Thread(target=reader, name="asr-reader", daemon=True)
        t1.start()
        t2.start()
        self._threads = [t1, t2]
