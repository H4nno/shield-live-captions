"""Live German→English caption server for the Shield overlay app.

Pipeline:
  audio source (USB line-in or file) → streaming ASR (de-DE) → sentence segmenter
  → per-line translation (llama-server) → WebSocket events for the Android overlay.

Events sent to clients:
  {"type": "partial", "text": "..."}                 current interim (German)
  {"type": "final",  "text": "...", "original": "...", "t": 169...}
                                                     English line + German original
  {"type": "status", "state": "...", "clients": n}

Run:
  python main.py --source capture --device 3          # live line-in
  python main.py --source file --file movie.mkv       # benchmark / dry-run
  python main.py --list-devices
"""
import argparse
import asyncio
import json
import logging
import os
import threading
import time
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from hub import Hub
from record import Recorder
from segment import Segmenter
from translate import Translator
from webui import PAGE

LANG_NAMES = {
    "de-DE": "German", "en-US": "English", "en-GB": "English", "fr-FR": "French",
    "es-ES": "Spanish", "it-IT": "Italian", "pt-BR": "Portuguese", "pt-PT": "Portuguese",
    "nl-NL": "Dutch", "tr-TR": "Turkish", "ru-RU": "Russian", "pl-PL": "Polish",
    "auto": "German",
}

SHIELDCC_HOME = os.environ.get("SHIELDCC_HOME", os.path.expanduser("~/shieldcc"))
SETTINGS_FILE = os.path.join(SHIELDCC_HOME, "settings.json")

DEFAULT_STYLE = {
    "fontSp": 28,
    "textColor": "#FFFFFF",
    "bgColor": "#000000",
    "bgAlpha": 70,
    "widthPct": 92,
    "position": 0,
}


def get_style() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            style = json.load(f).get("style")
        if isinstance(style, dict):
            merged = dict(DEFAULT_STYLE)
            merged.update({k: style[k] for k in DEFAULT_STYLE if k in style})
            return merged
    except Exception:
        pass
    return dict(DEFAULT_STYLE)


def apply_style_dict(body: dict) -> dict:
    style = get_style()
    for k in DEFAULT_STYLE:
        if k in body:
            try:
                if k in ("textColor", "bgColor"):
                    v = str(body[k])
                    if not v.startswith("#") or len(v) != 7:
                        continue
                    style[k] = v
                else:
                    style[k] = int(body[k])
            except (TypeError, ValueError):
                continue
    # persist inside settings.json
    data = {}
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    except Exception:
        pass
    data["style"] = style
    save_persisted_settings(data)
    return style


def apply_settings_dict(engine, translator, body: dict) -> None:
    if "lang" in body and engine.asr is not None:
        engine.asr.language = str(body["lang"])
        translator.source_name = LANG_NAMES.get(str(body["lang"]), "German")
        log.info("settings: asr lang=%s (applies to upcoming audio)", body["lang"])
    if "caption_lang" in body:
        translator.target_name = str(body["caption_lang"])
        log.info("settings: caption lang=%s", translator.target_name)
    if "draft_every_s" in body:
        engine.draft_every_s = min(max(float(body["draft_every_s"]), 0.0), 10.0)
    if "gap_finalize_s" in body:
        engine.segmenter.gap_finalize_s = min(max(float(body["gap_finalize_s"]), 0.0), 10.0)
    if "settle_s" in body:
        engine.segmenter.settle_s = min(max(float(body["settle_s"]), 0.0), 5.0)
    if "silence_rms" in body:
        engine.silence_rms = min(max(float(body["silence_rms"]), 0.00005), 0.05)
    if "silence_clear_s" in body:
        engine.silence_clear_s = min(max(float(body["silence_clear_s"]), 0.5), 60.0)
    if "max_sentence_len" in body:
        engine.segmenter.max_sentence_len = min(max(int(body["max_sentence_len"]), 40), 400)


def load_persisted_settings(engine, translator) -> None:
    try:
        with open(SETTINGS_FILE) as f:
            body = json.load(f)
        apply_settings_dict(engine, translator, body)
        log.info("persisted settings applied: %s", body)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("could not apply persisted settings: %s", e)


def save_persisted_settings(body: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(body, f, indent=1)
    except Exception as e:
        log.warning("could not persist settings: %s", e)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("shieldcc.main")

STATE = {
    "state": "init",
    "started_at": None,
    "source": None,
    "last_partial_at": None,
    "last_final_at": None,
    "sentences": 0,
    "translated": 0,
    "fallbacks": 0,
}


class StubAsr:
    """Stand-in for the real model: emits scripted German sentences word by word,
    starting when the first audio arrives. For pipeline/overlay dry-runs without GPU."""

    SENTENCES = [
        "Guten Abend, meine Damen und Herren. Willkommen zur Spätausgabe.",
        "Die Polizei gab heute bekannt, dass die Ermittlungen weiterlaufen.",
        "In Berlin wurde ein neues Gesetz verabschiedet, das im Januar in Kraft tritt.",
        "Das Wetter bleibt wechselhaft, mit Schauern in den nördlichen Regionen.",
        "Zum Schluss noch ein Blick auf die Börse: Der DAX schloss leicht im Plus.",
    ]

    def __init__(self, on_delta):
        self.on_delta = on_delta
        self.sampling_rate = 16000
        self._thread = None

    def feed_audio(self, chunk):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="stub-asr", daemon=True)
            self._thread.start()

    def finish(self):
        pass

    def wait_done(self):
        if self._thread:
            self._thread.join()

    def _run(self):
        import itertools
        import random

        time.sleep(1.0)
        for sentence in itertools.cycle(self.SENTENCES):
            words = sentence.split(" ")
            for i, w in enumerate(words):
                time.sleep(0.45 + random.random() * 0.3)
                sep = " " if i < len(words) - 1 else ""
                self.on_delta(w + sep)
            time.sleep(1.5)


class CaptionEngine:
    def __init__(self, hub: Hub, translator: Translator, loop: asyncio.AbstractEventLoop,
                 echo: bool = False, silence_rms: float = 0.001,
                 silence_flush_s: float = 2.5, silence_clear_s: float = 5.0,
                 draft_every_s: float = 1.0, gap_finalize_s: float = 1.8,
                 settle_s: float = 0.5):
        self.hub = hub
        self.translator = translator
        self.loop = loop
        self.echo = echo
        self.asr = None
        self.silence_rms = silence_rms
        self.silence_flush_s = silence_flush_s
        self.silence_clear_s = silence_clear_s
        self._last_voice = time.time()
        self._flushed = True   # don't flush/clear before the first speech
        self._cleared = True

        # live-draft translation state
        self._interim_de = ""
        self._draft_seq = 0
        self._draft_busy = False
        self._last_draft_src = None
        self.draft_every_s = draft_every_s

        # late tail words amend the PREVIOUS sentence instead of opening a new one
        self._last_final_original = None
        self._last_final_t = 0.0
        self._last_level_pub = 0.0

        self.recorder: Optional[Recorder] = None

        self.segmenter = Segmenter(
            on_partial=self._on_partial, on_sentence=self._on_sentence,
            gap_finalize_s=gap_finalize_s, settle_s=settle_s,
        )
        t = threading.Thread(target=self._draft_loop, name="draft-loop", daemon=True)
        t.start()

    # ---------- live English drafts ----------

    def _draft_loop(self) -> None:
        """Ticks 3x/sec: drives gap-based sentence finalization, and every
        draft_every_s translates the current German interim into a live draft."""
        import time as _t

        last_draft = 0.0
        while True:
            _t.sleep(0.3)
            try:
                self.segmenter.check_settle()
                self.segmenter.check_gap()
            except Exception:
                log.debug("segmenter tick failed", exc_info=True)

            if self.draft_every_s <= 0:
                continue
            if _t.time() - last_draft < self.draft_every_s:
                continue
            text = self._interim_de.strip()
            if len(text.split()) < 5:   # avoid hectic one-word drafts
                continue
            if text == self._last_draft_src or self._draft_busy:
                continue
            self._draft_busy = True
            last_draft = _t.time()
            seq = self._draft_seq
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._translate_draft(text, seq), self.loop)
                fut.add_done_callback(lambda f: self._draft_done(f))
            except RuntimeError:
                self._draft_busy = False

    def _draft_done(self, fut) -> None:
        self._draft_busy = False
        exc = fut.exception()
        if exc:
            log.debug("draft translation failed: %s", exc)

    async def _translate_draft(self, text: str, seq: int) -> None:
        english, ok = await self.translator.translate(text)
        if seq != self._draft_seq:
            return  # a sentence finalized meanwhile — the final will replace this
        self._last_draft_src = text
        self.hub.publish({"type": "partial_en", "text": english, "t": time.time()})

    def on_level(self, rms: float) -> None:
        """Called from the capture thread with the current input RMS."""
        now = time.time()
        if now - self._last_level_pub > 1.0:
            self._last_level_pub = now
            try:
                asyncio.run_coroutine_threadsafe(
                    self._emit_async({"type": "level", "rms": round(rms, 5), "t": now}),
                    self.loop)
            except RuntimeError:
                pass
        if rms >= self.silence_rms:
            self._last_voice = now
            self._flushed = False
            self._cleared = False
        else:
            quiet = now - self._last_voice
            if not self._flushed and quiet > self.silence_flush_s:
                self._flushed = True
                # finalize a leftover sentence fragment so it still gets translated
                self.segmenter.flush()
            if not self._cleared and quiet > self.silence_clear_s:
                self._cleared = True
                self._emit({"type": "clear", "t": now})

    # ---------- called by ASR thread ----------

    def on_delta(self, delta: str) -> None:
        self.segmenter.feed(delta)

    def feed_audio(self, chunk) -> None:
        if self.recorder is not None and self.recorder.audio_active:
            self.recorder.write_audio(chunk)
        self.asr.feed_audio(chunk)

    def finish(self) -> None:
        self.asr.finish()

    # ---------- segmenter callbacks (ASR thread) ----------

    def _emit(self, event: dict) -> None:
        asyncio.run_coroutine_threadsafe(self._emit_async(event), self.loop).result(timeout=10)

    async def _emit_async(self, event: dict) -> None:
        if self.echo:
            t = event.get("type")
            if t == "partial":
                log.info("PARTIAL  %s", event["text"])
            elif t == "final":
                log.info("FINAL    %s   [%s]", event["text"], event.get("original", ""))
        self.hub.publish(event)
        if self.recorder is not None:
            self.recorder.on_event(event)

    def _on_partial(self, text: str, at: float) -> None:
        STATE["last_partial_at"] = at
        self._interim_de = text
        self._emit({"type": "partial", "text": text, "t": at})

    def _on_sentence(self, sentence: str, at: float) -> None:
        now = time.time()
        # a short fragment shortly after a final is the late tail of the
        # PREVIOUS sentence — amend that line instead of starting a new one
        if (self._last_final_original is not None
                and len(sentence.split()) <= 3
                and now - self._last_final_t < 3.0):
            merged = (self._last_final_original.rstrip(".!?… ") + " " + sentence).strip()
            self._last_final_original = merged
            self._draft_seq += 1
            self._interim_de = ""
            self._last_draft_src = None
            self._emit({"type": "partial", "text": merged, "t": at})
            fut = asyncio.run_coroutine_threadsafe(self._translate_amend(merged, at), self.loop)
            fut.add_done_callback(lambda f: f.exception() and log.warning("amend failed: %s", f.exception()))
            return

        self._last_final_original = sentence
        self._last_final_t = now
        STATE["sentences"] += 1
        self._draft_seq += 1
        self._interim_de = ""
        self._last_draft_src = None
        # show the German sentence immediately as a partial so nothing flickers,
        # then replace it with the translation once it lands
        self._emit({"type": "partial", "text": sentence, "t": at})
        fut = asyncio.run_coroutine_threadsafe(
            self._translate_and_emit(sentence, at), self.loop
        )

        def _cb(done):
            exc = done.exception()
            if exc:
                log.error("translation task failed: %s", exc)

        fut.add_done_callback(_cb)

    async def _translate_amend(self, merged: str, at: float) -> None:
        t0 = time.time()
        english, ok = await self.translator.translate(merged)
        dt = time.time() - t0
        STATE["last_final_at"] = time.time()
        event = {
            "type": "final_amend",
            "text": english,
            "original": merged,
            "t": at,
            "translate_s": round(dt, 2),
            "machine": ok,
        }
        self.hub.publish(event)
        if self.recorder is not None:
            self.recorder.on_event(event)
        if was_translated:
            self.translator.set_context(english)

    async def _translate_and_emit(self, sentence: str, at: float) -> None:
        t0 = time.time()
        english, was_translated = await self.translator.translate(sentence)
        dt = time.time() - t0
        if was_translated:
            STATE["translated"] += 1
        else:
            STATE["fallbacks"] += 1
        STATE["last_final_at"] = time.time()
        event = {
            "type": "final",
            "text": english,
            "original": sentence,
            "t": at,
            "translate_s": round(dt, 2),
            "machine": was_translated,
        }
        self.hub.publish(event)
        if self.recorder is not None:
            self.recorder.on_event(event)
        if was_translated:
            self.translator.set_context(english)
        if self.echo:
            log.info("FINAL    %s   [%s] (+%.2fs)", english, sentence, dt)


async def amain(args, hub: Hub, translator: Translator, engine: Optional[CaptionEngine]):
    import uvicorn

    app = FastAPI(title="shieldcc")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(PAGE)

    def _settings() -> dict:
        return {
            "lang": engine.asr.language if engine.asr else "de-DE",
            "caption_lang": translator.target_name,
            "draft_every_s": engine.draft_every_s,
            "gap_finalize_s": engine.segmenter.gap_finalize_s,
            "settle_s": engine.segmenter.settle_s,
            "silence_rms": engine.silence_rms,
            "silence_clear_s": engine.silence_clear_s,
            "max_sentence_len": engine.segmenter.max_sentence_len,
        }

    @app.get("/api/settings")
    async def get_settings():
        return _settings()

    @app.post("/api/settings")
    async def apply_settings(req: Request):
        body = await request_json(req)
        try:
            apply_settings_dict(engine, translator, body)
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        merged = _settings()
        save_persisted_settings(merged)
        return {"ok": True, "settings": merged}

    async def request_json(req: Request) -> dict:
        try:
            return await req.json()
        except Exception:
            return {}

    @app.post("/api/record/start")
    async def record_start(audio: bool = False):
        return engine.recorder.start(with_audio=audio) if engine.recorder else {"error": "no recorder"}

    @app.post("/api/record/stop")
    async def record_stop():
        return engine.recorder.stop() if engine.recorder else {"error": "no recorder"}

    @app.get("/api/record/status")
    async def record_status():
        return engine.recorder.status() if engine.recorder else {"active": False}

    @app.get("/api/style")
    async def style_get():
        return get_style()

    @app.post("/api/style")
    async def style_set(req: Request):
        body = await request_json(req)
        style = apply_style_dict(body)
        hub.publish({"type": "style", "style": style, "t": time.time()})
        return {"ok": True, "style": style}

    @app.get("/api/record/srt")
    async def record_srt():
        if not engine.recorder:
            return PlainTextResponse("")
        return PlainTextResponse(
            engine.recorder.srt(),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=subtitles.srt"},
        )

    @app.get("/api/record/wav")
    async def record_wav():
        st = engine.recorder.status() if engine.recorder else {}
        path = st.get("wav")
        if not path:
            return PlainTextResponse("no audio recorded", status_code=404)
        return FileResponse(path, media_type="audio/wav", filename="recording.wav")

    @app.get("/healthz")
    async def healthz():
        return {
            "ok": True,
            "state": STATE,
            "clients": hub.client_count,
            "translator_stats": translator.stats,
        }

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        q = await hub.subscribe()
        log.info("client connected (%d total)", hub.client_count)
        recv_task = push_task = None
        try:
            await ws.send_json({"type": "status", "state": STATE["state"],
                                "clients": hub.client_count, "style": get_style()})
            recv_task = asyncio.create_task(ws.receive_text())
            push_task = asyncio.create_task(q.get())
            while True:
                done, _ = await asyncio.wait(
                    {recv_task, push_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if push_task in done:
                    await ws.send_json(push_task.result())
                    push_task = asyncio.create_task(q.get())
                if recv_task in done:
                    try:
                        msg = recv_task.result()
                    except WebSocketDisconnect:
                        break
                    try:
                        data = json.loads(msg) if msg else {}
                    except ValueError:
                        data = {}
                    if data.get("cmd") == "caption_lang":
                        val = str(data.get("value", "English"))
                        apply_settings_dict(engine, translator, {"caption_lang": val})
                        merged = {k: v for k, v in _settings().items()}
                        save_persisted_settings(merged)
                        log.info("caption_lang -> %s (from overlay app)", val)
                        await ws.send_json({"type": "status", "caption_lang": val})
                    recv_task = asyncio.create_task(ws.receive_text())
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.warning("client error: %s", e)
        finally:
            hub.unsubscribe(q)
            for t in (recv_task, push_task):
                if t is not None:
                    t.cancel()
            log.info("client disconnected (%d total)", hub.client_count)

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level=args.log_level)
    server = uvicorn.Server(config)
    await server.serve()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["capture", "file", "none"], default="capture")
    ap.add_argument("--file", help="media file for --source file")
    ap.add_argument("--device", type=int, default=None, help="sounddevice input index")
    ap.add_argument("--alsa-device", default=None,
                    help="capture via arecord from this ALSA device (e.g. hw:1,0) — "
                         "preferred for Scarlett interfaces; overrides --device")
    ap.add_argument("--alsa-channels", type=int, default=18)
    ap.add_argument("--alsa-rate", type=int, default=44100)
    ap.add_argument("--gain", type=float, default=1.0, help="input gain multiplier")
    ap.add_argument("--silence-rms", type=float, default=0.001,
                    help="RMS below this counts as silence (clear captions after a pause)")
    ap.add_argument("--silence-clear-s", type=float, default=5.0,
                    help="seconds of silence before captions are cleared")
    ap.add_argument("--draft-every-s", type=float, default=1.0,
                    help="interval for live English draft translations of the interim (0=off)")
    ap.add_argument("--gap-finalize-s", type=float, default=1.8,
                    help="speaker pause in seconds that finalizes a sentence without punctuation (0=off)")
    ap.add_argument("--settle-s", type=float, default=0.5,
                    help="quiet time before a punctuation split is applied (catches late last words)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--lang", default="de-DE")
    ap.add_argument("--lookahead", type=int, default=6,
                    help="streaming lookahead tokens (6 ≈ 560 ms extra latency)")
    ap.add_argument("--model", default="nvidia/nemotron-3.5-asr-streaming-0.6b")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--translate-url", default=None,
                    help="OpenAI-compatible server for DE→EN (e.g. http://127.0.0.1:8801). "
                         "Omit to pass German through untranslated.")
    ap.add_argument("--translate-model", default="local")
    ap.add_argument("--realtime", action="store_true", help="file source: pace like live playback")
    ap.add_argument("--echo", action="store_true", help="print partials/finals to stdout")
    ap.add_argument("--cpu", action="store_true", help="run ASR on CPU (slow, debugging only)")
    ap.add_argument("--stub", action="store_true",
                    help="no GPU/model: emit scripted German sentences (pipeline + overlay dry-run)")
    ap.add_argument("--log-level", default="warning", help="uvicorn log level")
    args = ap.parse_args()

    if args.list_devices:
        from capture import list_devices

        for d in list_devices():
            print(f"[{d['index']}] {d['name']}  (in: {d['channels_in']}, {d['default_sr']} Hz)")
        return

    hub = Hub()
    translator = Translator(args.translate_url, args.translate_model)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    engine = CaptionEngine(
        hub, translator, loop, echo=args.echo,
        silence_rms=args.silence_rms, silence_clear_s=args.silence_clear_s,
        draft_every_s=args.draft_every_s, gap_finalize_s=args.gap_finalize_s,
        settle_s=args.settle_s,
    )
    engine.recorder = Recorder()
    load_persisted_settings(engine, translator)

    STATE["state"] = "loading-model"
    STATE["started_at"] = time.time()
    log.info("source=%s lang=%s lookahead=%d translate=%s",
             args.source, args.lang, args.lookahead, args.translate_url or "off")

    if args.stub:
        engine.asr = StubAsr(engine.on_delta)
        log.info("STUB MODE: scripted sentences, no model loaded")
    else:
        from asr_stream import StreamingAsr

        engine.asr = StreamingAsr(
            on_delta=engine.on_delta,
            model_id=args.model,
            language=args.lang,
            lookahead_tokens=args.lookahead,
            device="cpu" if args.cpu else "cuda",
        )
    loop.run_until_complete(translator.start())
    if args.stub and args.source == "none":
        # nothing will feed audio — wake the scripted emitter directly
        import numpy as np

        engine.feed_audio(np.zeros(1, dtype=np.float32))
    STATE["state"] = "running"
    STATE["source"] = args.source

    source = None
    if args.source == "capture":
        if args.alsa_device:
            from capture import ArecordSource

            source = ArecordSource(
                engine.feed_audio,
                alsa_device=args.alsa_device,
                channels=args.alsa_channels,
                native_sr=args.alsa_rate,
                gain=args.gain,
                on_level=engine.on_level,
            )
        else:
            from capture import CaptureSource

            source = CaptureSource(engine.feed_audio, device=args.device)
        source.start()
    elif args.source == "file":
        from file_source import FileSource

        if not args.file:
            ap.error("--file is required for --source file")
        source = FileSource(args.file, engine.feed_audio, realtime=args.realtime)
        source.start()

    try:
        loop.run_until_complete(amain(args, hub, translator, engine))
    except KeyboardInterrupt:
        pass
    finally:
        STATE["state"] = "stopping"
        if source is not None:
            if hasattr(source, "stop"):
                source.stop()
            else:  # file source: it ends by itself
                pass
        if engine.asr is not None:
            engine.finish()
        loop.run_until_complete(translator.stop())
        loop.close()
        log.info("bye")


if __name__ == "__main__":
    main()
