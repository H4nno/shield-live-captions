# Caption server for DGX Spark (aarch64 + CUDA).
# The NGC pytorch base provides torch with GB10/sm_121 kernels and CUDA 13.
#
# NOTE: USB line-in capture does not work well inside this container (PortAudio/ALSA
# device passthrough). Use the container for --source file benchmarking, or run the
# venv variant (deploy/box2-setup.sh) directly on the host for live capture.
#
#   docker build -t shieldcc .
#   docker run --rm --gpus all -p 8799:8799 -v $HOME/.cache/huggingface:/root/.cache/huggingface \
#     shieldcc --source none --echo
#   docker run --rm --gpus all -v $HOME/.cache/huggingface:/root/.cache/huggingface \
#     -v /path/to/movie.mkv:/tmp/movie.mkv shieldcc --source file --file /tmp/movie.mkv --echo

FROM nvcr.io/nvidia/pytorch:25.11-py3

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

EXPOSE 8799
ENTRYPOINT ["python", "main.py"]
CMD ["--source", "none", "--echo"]
