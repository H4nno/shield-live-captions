"""Feeds a media file's audio through the pipeline via ffmpeg.

--realtime paces the audio like live playback (for watching the overlay behave);
without it, audio is pushed as fast as the model consumes it (for benchmarking).
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger("shieldcc.filesource")


class FileSource:
    def __init__(self, path: str, on_chunk, realtime: bool = True):
        self.path = path
        self.on_chunk = on_chunk
        self.realtime = realtime
        self._proc = None
        self.thread = None

    def start(self) -> threading.Thread:
        self.thread = threading.Thread(target=self._run, name="file-source", daemon=True)
        self.thread.start()
        return self.thread

    def _run(self):
        cmd = [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-i", self.path,
            "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1",
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**6)
        chunk_bytes = 16000 * 4  # 1 s per chunk
        t0 = time.time()
        stream_pos = 0.0
        try:
            while True:
                data = self._proc.stdout.read(chunk_bytes)
                if not data:
                    break
                if len(data) % 4:
                    data = data[: len(data) - (len(data) % 4)]
                chunk = np.frombuffer(data, dtype=np.float32)
                if self.realtime:
                    stream_pos += chunk.size / 16000.0
                    behind = stream_pos - (time.time() - t0)
                    if behind > 0.05:
                        time.sleep(behind)
                self.on_chunk(chunk)
        finally:
            self._proc.stdout.close()
            self._proc.wait()
            log.info("file source done: %s", self.path)
