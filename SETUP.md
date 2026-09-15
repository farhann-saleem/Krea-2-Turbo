# Setup — Krea-2-Turbo

## Prerequisites

- Docker
- RunPod account + API key
- R2 credentials for the `comfy` weights bucket
- Network volume in **EU-RO-1** (~22 GB+ free for ~18 GB weights)

## Build locally

```bash
docker build -t ms-runpod-krea:local .
```

Local containers have no GPU and no volume — only import + `ping` are meaningful:

```bash
docker run --rm ms-runpod-krea:local \
  python /handler.py --test_input '{"input":{"op":"ping"}}'
```

Expect `volume_mounted: false` and a small `free_gb`. That is correct.

## Deploy

1. Push to `main`.
2. Create a GitHub **Release** (triggers RunPod rebuild).
3. Purge the queue and **stop old workers**.
4. Confirm the **worker id changed** before trusting the fix.

### Endpoint settings

| Setting | Value |
| --- | --- |
| Network volume | EU-RO-1 |
| Data centers | **EU-RO-1 only** |
| GPU | 24 GB |
| Min / max workers | 0 / 1 |
| Idle timeout | 5s prod · 60s+ while iterating |
| FlashBoot | on (still recycle after rebuild) |
| Execution timeout | 600s |

Cross-DC volume + GPU = silent `Initializing`, empty logs.

## Environment (names only)

See [`.env.example`](.env.example). Paste values on the endpoint Environment tab — never in git.

| Name | Purpose |
| --- | --- |
| `ALLOW_GENERATE` | Keep `0` for first console tests |
| `R2_ACCOUNT_ID` / `R2_ENDPOINT` | R2 access |
| `R2_ACCESS_KEY` / `R2_SECRET_KEY` | credentials |
| `R2_BUCKET` | default `comfy` (`R2_BUCKET_NAME` wins) |
| `RUNPOD_GPU_USD_PER_HR` | estimate basis, default `0.69` |
| `COMFY_DIR` | default `/workspace/ComfyUI` |

`HF_TOKEN` is not needed at runtime. Do not bake it into the image.

## Smoke sequence

```
GET /health            → stop if throttled > 0
POST /run {op: ping}   → volume_mounted, comfy_up, free_gb >> 22
POST /run {op: generate, prompt: "…"} → poll /status/{id}
```

Never spam generate while `throttled > 0`.

## Generate example

```python
import base64, os, time, requests

ENDPOINT = "i3fvrhucaici89"
HEADERS = {"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}"}

job = requests.post(
    f"https://api.runpod.ai/v2/{ENDPOINT}/run",
    headers=HEADERS,
    json={"input": {"op": "generate", "prompt": "a lime neon sign in heavy rain", "steps": 4}},
    timeout=30,
).json()["id"]

while True:
    time.sleep(5)
    s = requests.get(f"https://api.runpod.ai/v2/{ENDPOINT}/status/{job}", headers=HEADERS).json()
    if s["status"] == "COMPLETED":
        open("out.png", "wb").write(base64.b64decode(s["output"]["png_b64"]))
        break
    if s["status"] == "FAILED":
        raise SystemExit(s.get("error"))
```

## Troubleshooting (short)

| Symptom | Fix |
| --- | --- |
| `Initializing`, no logs | Pin DC to volume’s DC only |
| `Errno 28` / `free_gb ≈ 5` | Real network volume + stop old workers |
| `value_not_in_list — type` | CLIP type is `krea2` |
| Same error, same worker id | Purge, stop workers, verify new id |

Full table: app [`docs/RUNPOD.md`](https://github.com/farhann-saleem/sixeyes/blob/main/docs/RUNPOD.md).
