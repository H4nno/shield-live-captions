# Live Captions for Android TV

Real-time translated subtitles for any app on your TV box — including
DRM-protected playback (Netflix, Prime Video, Disney+). Built and tested on an
NVIDIA Shield (2019, Android TV 11) with a DGX Spark as the compute host.

```
                TV audio (tapped after the box)
                              │
   AVR/extractor pre-out ──► USB audio interface ──► GPU host
                              │                        │  arecord 16 kHz mono
                              │                        │  nvidia/nemotron-3.5-asr-streaming-0.6b
                              │                        │  (true streaming ASR, sub-second)
                              │                        │  sentence segmentation
                              │                        │  LLM translation (llama.cpp / vLLM / …)
                              ▼                        ▼
                    Android TV overlay app ◄── WebSocket (ws://host:8799/ws)
                    (TYPE_APPLICATION_OVERLAY, renders over DRM video)
```

**Example:** German TV audio in → English captions on the Shield ~1–2 s after
each sentence, with a live draft line updating while people speak. Languages
are switchable at runtime (ASR: 10+ locales incl. pt-BR; caption target:
whatever your translation LLM speaks).

## Why this exists

- Android blocks on-device capture of DRM playback, so audio is tapped
  *outside* the box (AVR pre-out / HDMI extractor) — works for every app.
- The overlay is a plain `TYPE_APPLICATION_OVERLAY` window, granted via adb
  `appops` — no root, and it demonstrably renders over Widevine video.
- The ASR model is NVIDIA's open streaming model
  ([nemotron-3.5-asr-streaming-0.6b](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b),
  OpenMDW license): true cache-aware streaming with configurable latency
  (80 ms–1.12 s), running via 🤗 Transformers ≥ 5.13 on CUDA — including
  aarch64 (DGX Spark).

## Repository layout

| Path | What |
|---|---|
| `app/` | Android TV app (Java, zero dependencies): overlay service, hand-rolled RFC 6455 WebSocket client, broadcast toggles, leanback settings |
| `server/` | Python server: capture / file / stub source → streaming ASR → segmentation → translation → WebSocket events, plus a web control panel |
| `scripts/setup-server.sh` | Provision the server on a Linux GPU host |
| `scripts/install-app.sh` | Build + install the app on the TV box via adb |
| `docs/audio-tapping.md` | How to get TV audio into the host (AVR pre-out, HDMI extractor, interface quirks) |

## Quick start

### 1. Server (any Linux CUDA host; aarch64 works)

```bash
git clone <this repo> && cd shield-live-captions
bash scripts/setup-server.sh                       # deps + venv + ~/shieldcc
~/shieldcc/.venv/bin/python ~/shieldcc/main.py --list-devices   # find your interface
~/shieldcc/.venv/bin/python ~/shieldcc/main.py --source file --file movie.mkv --echo   # dry run
```

Optional but recommended — a translation server (any OpenAI-compatible
endpoint; a ~4B instruct GGUF in llama-server is plenty):

```bash
llama-server -m qwen3-4b-instruct-q4_k_m.gguf --alias shield-translate \
  --host 127.0.0.1 --port 8801 -ngl 99 -c 4096 --temp 0.1
```

Then edit `~/shieldcc/run.sh` (audio device parameters, `TRANSLATE_URL`) and
start it. Open `http://host:8799/` for the control panel: live view, level
meter, all timing/language settings, style editor, and SRT+WAV recording.

### 2. App (Android TV box)

```bash
./gradlew :app:assembleDebug
./scripts/install-app.sh <tv-box-ip>     # enables "adb over network" once on the box
```

Set the server address in the app's settings screen, press Start — captions
appear over whatever you're watching.

### 3. Daily use

- The app auto-starts on boot and reconnects to the server on its own.
- Remote toggles (adb, or any button-mapper app that can send intents):
  `app.shieldcc.action.START` / `STOP` / `TOGGLE` / `SIZE_UP` / `SIZE_DOWN` /
  `CYCLE_POSITION` / `MODE` (EN+DE / EN only / DE only) / `LANG_CYCLE`
  (off → English → Portuguese → off, switches the translation target over the
  WebSocket).
- Web panel: language, rhythm (drafts, sentence splitting, silence clearing),
  overlay style (size/colors/width/position), recording with SRT download.

## Gotchas learned the hard way

- **`from __future__ import annotations` + FastAPI websocket handlers whose
  types are imported inside a function** → FastAPI resolves string annotations
  in module scope, silently closes the websocket (403, no traceback).
- **Android:** `screencap` returns nothing over DRM video; verify overlays via
  `dumpsys window windows | grep <pkg>` (`mViewVisibility=0x0` = visible).
  Shell broadcasts don't reach freshly installed (stopped-state) apps — the
  service is exported so `am start-foreground-service` works directly.
  Network I/O in `onStartCommand` throws `NetworkOnMainThreadException` —
  send WS commands from a worker thread.
- **Audio interfaces:** some (Focusrite Scarlett 4th gen) only deliver real
  input samples in *some* ALSA altsettings — e.g. `hw:1,0` at `-c 10 -f S32_LE
  -r 176400`; the default 18-channel altsetting delivers noise on every
  channel, and requesting an unsupported rate silently records at another one
  (chipmunk audio). Verify with `arecord … -d 5 test.wav` +
  `ffmpeg -volumedetect` before blaming the ASR. Details in
  `docs/audio-tapping.md`.
- **AVRs:** many receivers (e.g. Marantz SR5011) route only analog/network
  sources to Zone 2 — HDMI audio never reaches it, not even with "All Zone
  Stereo". The main-zone **front L/R pre-out** always carries everything.

## Credits & licenses

- Code: MIT (see `LICENSE`).
- ASR model: `nvidia/nemotron-3.5-asr-streaming-0.6b` (OpenMDW).
- Translation: whatever OpenAI-compatible LLM you point it at.

Not affiliated with NVIDIA, Google or Focusrite. Please respect the content
licenses of whatever you caption — this is a personal accessibility tool.
