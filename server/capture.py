"""Line-in capture from a USB sound card via sounddevice/PortAudio.

Opens the device at its native rate in mono and resamples to 16 kHz with
scipy resample_poly before handing chunks to the ASR.
"""
from __future__ import annotations

import logging
import queue
import subprocess
import threading

import numpy as np

log = logging.getLogger("shieldcc.capture")

TARGET_SR = 16000


def list_devices() -> list[dict]:
    import sounddevice as sd

    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] >= 1:
            out.append({
                "index": i,
                "name": d["name"],
                "channels_in": d["max_input_channels"],
                "default_sr": int(d["default_samplerate"]),
            })
    return out


class CaptureSource:
    def __init__(self, on_chunk, device: int | None = None, block_ms: float = 40.0):
        """
        on_chunk: callable(np.ndarray float32 @16k mono)
        device: sounddevice input index (None = system default input)
        """
        self.on_chunk = on_chunk
        self.device = device
        self.block_ms = block_ms
        self._stream = None
        self._resample_state: list[int] = []  # [gcd, up, down] computed on first callback
        self._overflow_count = 0

    def start(self):
        import sounddevice as sd

        dev = sd.query_devices(kind="input") if self.device is None else sd.query_devices(self.device)
        native_sr = int(dev["default_samplerate"])
        max_ch = int(dev["max_input_channels"])
        from math import gcd

        g = gcd(native_sr, TARGET_SR)
        self._rs = (TARGET_SR // g, native_sr // g)  # (up, down) for resample_poly

        blocksize = int(native_sr * self.block_ms / 1000.0)
        log.info(
            "capture start: device=%s (%s) native_sr=%d blocksize=%d max_ch=%d",
            self.device, dev["name"], native_sr, blocksize, max_ch,
        )

        def callback(indata, frames, time_info, status):
            if status:
                self._overflow_count += 1
                if self._overflow_count % 50 == 1:
                    log.warning("capture status: %s (x%d)", status, self._overflow_count)
            self._deliver(indata[:, 0].copy(), native_sr)

        # Some interfaces (e.g. Scarlett hw devices) accept their native stream
        # only at the full channel count and deliver silence otherwise —
        # try all channels first, then mono.
        for channels in [max_ch, 1]:
            try:
                self._stream = sd.InputStream(
                    samplerate=native_sr,
                    channels=channels,
                    dtype="float32",
                    blocksize=blocksize,
                    device=self.device,
                    callback=callback,
                )
                self._stream.start()
                log.info("capture open: %d channel(s)", channels)
                return
            except Exception as e:
                log.warning("capture open with %d channel(s) failed: %s", channels, e)
        raise RuntimeError(f"could not open capture device {self.device} ({dev['name']})")

    def _deliver(self, chunk: np.ndarray, native_sr: int):
        from scipy.signal import resample_poly

        up, down = self._rs
        mono16k = resample_poly(chunk, up, down).astype(np.float32)
        if mono16k.size:
            self.on_chunk(mono16k)

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            log.info("capture stopped")


class ArecordSource:
    """Capture via `arecord` raw stdout. Works where PortAudio refuses or
    delivers silence (Scarlett hw:1,0 needs its full channel count at S32_LE).

    on_chunk: callable(np.ndarray float32 @16k mono), channel 0 of the stream.
    """

    def __init__(self, on_chunk, alsa_device: str = "hw:1,0", channels: int = 18,
                 native_sr: int = 44100, gain: float = 1.0, on_level=None):
        self.on_chunk = on_chunk
        self.alsa_device = alsa_device
        self.channels = channels
        self.native_sr = native_sr
        self.gain = gain
        self.on_level = on_level
        self._proc = None
        self.thread = None
        self._rs = None

    def start(self):
        from math import gcd

        g = gcd(self.native_sr, TARGET_SR)
        self._rs = (TARGET_SR // g, self.native_sr // g)
        cmd = [
            "arecord", "-D", self.alsa_device,
            "-c", str(self.channels), "-f", "S32_LE", "-r", str(self.native_sr),
            "-t", "raw", "--buffer-size=16384", "-",
        ]
        log.info("arecord start: %s (%d ch, %d Hz)", self.alsa_device, self.channels, self.native_sr)
        self._err = open("/tmp/arecord_stderr.log", "wb")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=self._err, bufsize=10 ** 6)
        self.thread = threading.Thread(target=self._run, name="arecord-reader", daemon=True)
        self.thread.start()

    def _run(self):
        from scipy.signal import resample_poly

        frame_bytes = self.channels * 4 * 512  # 512 frames per read
        up, down = self._rs
        reads = 0
        rms_acc = []
        try:
            while True:
                data = self._proc.stdout.read(frame_bytes)
                if not data or len(data) % (self.channels * 4) != 0:
                    if not data:
                        break
                    data = data[: len(data) - (len(data) % (self.channels * 4))]
                raw = np.frombuffer(data, dtype=np.int32).reshape(-1, self.channels)
                mono = raw[:, 0].astype(np.float32) / 2147483648.0
                if self.gain != 1.0:
                    mono = np.clip(mono * self.gain, -1.0, 1.0)
                chunk16k = resample_poly(mono, up, down).astype(np.float32)
                if chunk16k.size:
                    self.on_chunk(chunk16k)
                rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
                if self.on_level is not None:
                    try:
                        self.on_level(rms)
                    except Exception:
                        pass
                rms_acc.append(rms)
                reads += 1
                if reads % 100 == 0:  # ~ every 5 s at 512-frame reads
                    log.info("capture level: rms=%.5f peak_abs=%d reads=%d",
                             sum(rms_acc) / len(rms_acc), int(np.max(np.abs(raw))), reads)
                    rms_acc = []
        finally:
            log.info("arecord reader stopped after %d reads", reads)
            try:
                self._proc.stdout.close()
                self._proc.terminate()
            except Exception:
                pass

    def stop(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
