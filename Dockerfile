# Assignment worker. Code only.
# Credentials: RunPod endpoint env at runtime — never COPY .env (see rika-voice Dockerfile).
# Weights: R2 / network volume — never COPY *.safetensors (30 min / 80 GB cap).
FROM python:3.11-slim

WORKDIR /
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
COPY handler.py /handler.py

CMD ["python", "-u", "/handler.py"]
