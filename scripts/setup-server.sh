#!/usr/bin/env bash
# Provision the caption server on a Linux GPU host (tested on aarch64 DGX Spark).
# Run ON the host:   bash scripts/setup-server.sh
set -euo pipefail
DEST="${SHIELDCC_HOME:-$HOME/shieldcc}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Installing system packages (needs sudo): portaudio19-dev, ffmpeg"
sudo apt-get update -qq
sudo apt-get install -y portaudio19-dev ffmpeg

echo "==> Creating venv at $DEST/.venv"
python3 -m venv "$DEST/.venv"
# shellcheck disable=SC1091
source "$DEST/.venv/bin/activate"
pip install --upgrade pip

echo "==> Installing torch"
# aarch64 CUDA (DGX Spark, GB10):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
# x86_64 NVIDIA hosts can simply use: pip install torch torchaudio

echo "==> Installing python deps"
pip install -r "$SRC/server/requirements.txt"

mkdir -p "$DEST"
cp "$SRC"/server/*.py "$DEST"/
cp "$SRC"/server/requirements.txt "$DEST"/

cat > "$DEST/run.sh" <<'EOF'
#!/usr/bin/env bash
# Live capture -> streaming ASR -> translation -> WebSocket on :8799
# Adjust --alsa-device/-c/-r to your interface (see README, "Audio interfaces").
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
exec python main.py \
  --source capture \
  --alsa-device hw:1,0 \
  --alsa-channels 10 \
  --alsa-rate 176400 \
  --translate-url "${TRANSLATE_URL:-}" \
  --translate-model "${TRANSLATE_MODEL:-local}" \
  --echo \
  --port "${PORT:-8799}"
EOF
chmod +x "$DEST/run.sh"
echo
echo "Done. Next steps:"
echo "  1. Find your audio device:   $DEST/.venv/bin/python $DEST/main.py --list-devices"
echo "  2. Smoke test with a file:   $DEST/.venv/bin/python $DEST/main.py --source file --file /path/movie.mkv --echo"
echo "  3. Translator (optional):    any OpenAI-compatible server, e.g."
echo "     llama-server -m <small-instruct.gguf> --alias shield-translate --port 8801 -ngl 99 -c 4096"
echo "  4. Live:                     edit $DEST/run.sh (device/channels/rate), then run it"
