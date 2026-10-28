"""Single-file control panel served by the caption server at /."""

PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>shieldcc</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:#0e0f12; color:#ddd; font:15px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { display:flex; align-items:center; gap:14px; padding:14px 20px; background:#15171c; border-bottom:1px solid #262a33; }
  header h1 { font-size:17px; margin:0; letter-spacing:.4px; }
  #live { font-size:12px; padding:3px 9px; border-radius:10px; background:#233; color:#9aa; }
  #live.on { background:#143; color:#7f8; }
  #meterwrap { flex:1; max-width:280px; height:10px; background:#22262e; border-radius:5px; overflow:hidden; }
  #meter { height:100%; width:0%; background:linear-gradient(90deg,#3f6,#fd3,#f33); transition:width .3s; }
  main { display:flex; gap:18px; padding:18px 20px; flex-wrap:wrap; }
  #captions { flex: 1 1 420px; max-width:760px; }
  #draft { color:#9ab; min-height:24px; font-style:italic; opacity:.9; margin-bottom:8px; }
  #finals { list-style:none; margin:0; padding:0; }
  #finals li { padding:7px 10px; border-left:3px solid #37506e; margin-bottom:6px; background:#151820; border-radius:4px; }
  #finals li .orig { display:block; color:#788; font-size:12.5px; margin-top:2px; }
  #finals li .t { color:#566; font-size:11px; font-family:monospace; margin-right:8px; }
  .card { flex:0 1 340px; background:#15171c; border:1px solid #262a33; border-radius:8px; padding:14px 16px; margin-bottom:16px; }
  .card h2 { font-size:14px; margin:0 0 10px; color:#9ab; text-transform:uppercase; letter-spacing:.8px; }
  label { display:block; font-size:12.5px; color:#9aa; margin:9px 0 3px; }
  .hint { font-size:11.5px; color:#66707e; line-height:1.35; margin:3px 0 2px; }
  select, input[type=number] { width:100%; background:#0e0f12; color:#ddd; border:1px solid #333a47; border-radius:5px; padding:6px 8px; font-size:14px; }
  .row2 { display:flex; gap:10px; } .row2 > div { flex:1; }
  button { background:#2c4a6e; border:none; color:#dfe; padding:8px 14px; border-radius:5px; font-size:14px; cursor:pointer; margin-top:10px; }
  button:hover { background:#38608e; }
  button.warn { background:#6e3a2c; } button.warn:hover { background:#8e4a38; }
  #recstate { font-size:13px; color:#9a9; margin-top:8px; }
  a.dl { display:none; margin-top:8px; margin-right:12px; color:#7cf; font-size:13.5px; }
  #toast { position:fixed; bottom:16px; right:16px; background:#143; color:#8fda; padding:9px 14px; border-radius:6px; opacity:0; transition:opacity .3s; }
</style>
</head><body>
<header>
  <h1>shieldcc — live captions</h1>
  <span id="live">connecting…</span>
  <div id="meterwrap"><div id="meter"></div></div>
</header>
<main>
  <section id="captions">
    <div id="draft"></div>
    <ul id="finals"></ul>
  </section>
  <aside style="flex:0 1 360px; min-width:300px;">
    <div class="card">
      <h2>Settings</h2>
      <div class="row2">
        <div><label>Audio language</label>
          <select id="lang">
            <option value="de-DE">German</option><option value="en-US">English (US)</option>
            <option value="en-GB">English (UK)</option><option value="fr-FR">French</option>
            <option value="es-ES">Spanish</option><option value="it-IT">Italian</option>
            <option value="pt-BR">Portuguese (Brazil)</option><option value="pt-PT">Portuguese (PT)</option>
            <option value="nl-NL">Dutch</option><option value="tr-TR">Turkish</option>
            <option value="ru-RU">Russian</option><option value="pl-PL">Polish</option>
            <option value="auto">Auto-detect</option>
          </select>
          <div class="hint">Language the speech recognition listens for. "Auto" detects it per utterance, but is less reliable than picking one.</div></div>
        <div><label>Caption language</label>
          <select id="caption_lang">
            <option value="English">English</option><option value="German">German</option>
            <option value="French">French</option><option value="Spanish">Spanish</option>
            <option value="Italian">Italian</option><option value="Portuguese">Portuguese</option>
            <option value="Dutch">Dutch</option><option value="Turkish">Turkish</option>
            <option value="Russian">Russian</option><option value="Polish">Polish</option>
          </select>
          <div class="hint">Target language of the translation. If it equals the audio language, translation is skipped entirely.</div></div>
      </div>
      <div class="row2">
        <div><label>Draft interval s (0=off)</label><input type="number" id="draft_every_s" step="0.5" min="0" max="6">
          <div class="hint">How often the still-growing sentence gets a quick draft translation shown as a dimmer line. 0 = no drafts, only finished sentences (calmest).</div></div>
        <div><label>Gap finalize s</label><input type="number" id="gap_finalize_s" step="0.1" min="0.3" max="4">
          <div class="hint">Speaking pause that finishes a sentence even without punctuation. Higher = longer lines, lower = faster cuts.</div></div>
      </div>
      <div class="row2">
        <div><label>Settle s</label><input type="number" id="settle_s" step="0.1" min="0.2" max="2">
          <div class="hint">Quiet time before a finished sentence is cut out of the stream — catches the last word when it arrives slightly late. Keep small (0.3–0.6).</div></div>
        <div><label>Silence clear s</label><input type="number" id="silence_clear_s" step="0.5" min="1" max="15">
          <div class="hint">Seconds of silence before the caption box disappears from the screen completely.</div></div>
      </div>
      <label>Silence RMS threshold</label><input type="number" id="silence_rms" step="0.0002" min="0.0001" max="0.01">
      <div class="hint">Audio level below this counts as silence (drives the clearing above). Lower the value if captions vanish during quiet dialogue, raise it if they linger over background music.</div>
      <div class="row2">
        <div><label>Max sentence length</label><input type="number" id="max_sentence_len" step="10" min="40" max="400">
          <div class="hint">Long sentences are split into display chunks of at most this many characters, cut at commas — keeps talkative speakers from filling the screen.</div></div>
      </div>
      <button id="apply">Apply</button>
      <button id="recommended" style="background:#2c5e3a; margin-left:8px;">Recommended settings</button>
    </div>
    <div class="card">
      <h2>Overlay style</h2>
      <div class="row2">
        <div><label>Font size (sp)</label><input type="number" id="fontSp" step="1" min="14" max="64">
          <div class="hint">Caption text size on the TV.</div></div>
        <div><label>Width (% of screen)</label><input type="number" id="widthPct" step="2" min="30" max="100">
          <div class="hint">Width of the caption box. Narrower = shorter lines, centered.</div></div>
      </div>
      <div class="row2">
        <div><label>Text color</label><input type="color" id="textColor" style="height:38px;padding:2px">
          <div class="hint">Color of the caption text (a soft shadow is always added for readability).</div></div>
        <div><label>Background</label><input type="color" id="bgColor" style="height:38px;padding:2px">
          <div class="hint">Background color of the caption box.</div></div>
      </div>
      <div class="row2">
        <div><label>Background opacity %</label><input type="number" id="bgAlpha" step="5" min="0" max="100">
          <div class="hint">0 = no box at all (floating text with shadow), 100 = solid box.</div></div>
        <div><label>Position</label>
          <select id="position"><option value="0">Bottom</option><option value="1">Lower third</option><option value="2">Top</option></select>
          <div class="hint">Vertical placement of the caption box on the screen.</div></div>
      </div>
      <button id="apply_style">Apply style</button>
      <button id="style_reset" class="warn" style="margin-left:8px;">Reset</button>
    </div>
    <div class="card">
      <h2>Record</h2>
      <label><input type="checkbox" id="rec_audio" style="width:auto" checked> also record audio (16 kHz WAV)</label>
      <div class="hint">Recording writes the finished captions to an .srt file; with the checkbox it also saves the audio as WAV. Neither affects the live captions' performance.</div>
      <button id="rec_start">Start recording</button>
      <button id="rec_stop" class="warn" style="display:none">Stop</button>
      <div id="recstate">idle</div>
      <a class="dl" id="dl_srt" href="/api/record/srt" download>⬇ subtitles.srt</a>
      <a class="dl" id="dl_wav" href="/api/record/wav" download>⬇ audio.wav</a>
    </div>
  </aside>
</main>
<div id="toast"></div>
<script>
const $ = id => document.getElementById(id);
let ws;
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { $("live").textContent = "live"; $("live").classList.add("on"); };
  ws.onclose = () => { $("live").textContent = "reconnecting…"; $("live").classList.remove("on"); setTimeout(connect, 1500); };
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.type === "level") { $("meter").style.width = Math.min(100, m.rms * 9000) + "%"; return; }
    if (m.type === "partial_en") { $("draft").textContent = m.text; return; }
    if (m.type === "partial") { if (!$("draft").textContent) $("draft").textContent = m.text; return; }
    if (m.type === "clear") { $("draft").textContent = ""; return; }
    if (m.type === "final") {
      $("draft").textContent = "";
      const li = document.createElement("li");
      const t = new Date(m.t * 1000).toLocaleTimeString();
      li.innerHTML = `<span class="t">${t}</span>${escapeHtml(m.text)}` +
        (m.original ? `<span class="orig">${escapeHtml(m.original)}</span>` : "");
      $("finals").prepend(li);
      while ($("finals").children.length > 9) $("finals").lastChild.remove();
    }
  };
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
function toast(msg) { const t = $("toast"); t.textContent = msg; t.style.opacity = 1; setTimeout(() => t.style.opacity = 0, 1800); }

async function loadSettings() {
  const r = await fetch("/api/settings"); const s = await r.json();
  for (const k of Object.keys(s)) { const el = $(k); if (el) el.value = s[k]; }
}
$("apply").onclick = async () => {
  const body = {};
  for (const k of ["lang","caption_lang","draft_every_s","gap_finalize_s","settle_s","silence_rms","silence_clear_s"])
    body[k] = $(k).value;
  const r = await fetch("/api/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  toast(r.ok ? "applied ✓" : "failed");
};
$("recommended").onclick = async () => {
  const rec = {draft_every_s: 2.0, gap_finalize_s: 1.8, settle_s: 0.5,
               silence_rms: 0.001, silence_clear_s: 5.0, max_sentence_len: 110};
  for (const k of Object.keys(rec)) $(k).value = rec[k];
  const r = await fetch("/api/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(rec)});
  toast(r.ok ? "recommended applied ✓" : "failed");
};
const STYLE_KEYS = ["fontSp","textColor","bgColor","bgAlpha","widthPct","position"];
async function loadStyle() {
  const r = await fetch("/api/style"); const s = await r.json();
  for (const k of STYLE_KEYS) { if ($(k)) $(k).value = s[k]; }
}
$("apply_style").onclick = async () => {
  const body = {};
  for (const k of STYLE_KEYS) body[k] = $(k).value;
  const r = await fetch("/api/style", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  toast(r.ok ? "style applied ✓" : "failed");
};
$("style_reset").onclick = async () => {
  const r = await fetch("/api/style", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({fontSp:28, textColor:"#FFFFFF", bgColor:"#000000", bgAlpha:70, widthPct:92, position:0})});
  await loadStyle();
  toast(r.ok ? "style reset ✓" : "failed");
};
loadStyle();
$("rec_start").onclick = async () => {
  await fetch(`/api/record/start?audio=${$("rec_audio").checked}`, {method:"POST"});
  recUI(true);
};
$("rec_stop").onclick = async () => {
  const r = await fetch("/api/record/stop", {method:"POST"});
  recUI(false);
};
function recUI(on) {
  $("rec_start").style.display = on ? "none" : "";
  $("rec_stop").style.display = on ? "" : "none";
  $("dl_srt").style.display = on ? "none" : "inline";
  $("recstate").textContent = on ? "● recording" : "stopped";
}
loadSettings(); connect();
setInterval(async () => {
  const r = await fetch("/api/record/status"); const s = await r.json();
  if (!s.active && $("recstate").textContent.startsWith("●")) recUI(false);
  if (s.active) $("recstate").textContent = `● recording — ${s.sentences} sentences`;
  $("dl_wav").style.display = s.wav ? "inline" : "none";
}, 2000);
</script>
</body></html>
"""
