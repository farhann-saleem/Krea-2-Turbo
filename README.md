# Krea-2-Turbo — text-to-image GPU worker

RunPod serverless worker that turns a prompt into an image. ComfyUI + Krea-2-Turbo fp8, weights streamed from
Cloudflare R2 onto a network volume.

One of four repositories in **Marketing Studio**, the 8x hiring assignment. This worker is the **T2I** leg.

| | |
| --- | --- |
| **Role** | `prompt → PNG` for the Marketing Studio app |
| **Runtime** | RunPod serverless GPU, ComfyUI v0.35.1, PyTorch 2.7.0, CUDA 12.8 |
| **Model** | Krea-2-Turbo, fp8 scaled, 4 steps, cfg 1.0, euler/simple |
| **Endpoint** | `i3fvrhucaici89` — **EU-RO-1 only** |
| **Weights** | ~18 GB on R2 under `comfy-models/krea2-turbo/`. Never in git, never in the image. |
| **Cost** | ~$0.002 per warm image at the assumed $0.69/GPU-hour |
| **Status** | Deployed. Text-to-image is not the app's default avatar path (OpenRouter FLUX.2 Klein 4B is), so this worker is exercised less than Qwen. |

---

## Where this fits

```
Marketing Studio backend
   │
   ├── text → image  ──────────►  THIS WORKER        (RunPod GPU)
   ├── image → image ──────────►  Qwen-and-QwenEdit  (RunPod GPU)
   ├── face swap / stitch ─────►  Faceswap-and-FF    (RunPod CPU)
   └── image → video  ─────────►  Modal LTX-2.5      (H200)
                                        │
                                  Cloudflare R2
                              weights + product media
```

| Sibling | Repo |
| --- | --- |
| Application tier | [`farhann-saleem/sixeyes`](https://github.com/farhann-saleem/sixeyes) |
| Image → image | [`farhann-saleem/Qwen-and-QwenEdit`](https://github.com/farhann-saleem/Qwen-and-QwenEdit) |
| CPU swap + stitch | [`farhann-saleem/Faceswap-and-FF`](https://github.com/farhann-saleem/Faceswap-and-FF) |

---

## API

Two ops. `op` defaults to `generate` when a `prompt` is present, otherwise `ping`.

### `ping` — readiness, no model work

```bash
curl -s https://api.runpod.ai/v2/i3fvrhucaici89/runsync \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"op":"ping"}}'
```

```json
{
  "ok": true,
  "worker": "krea",
  "comfy_up": true,
  "volume_mounted": true,
  "weight_root": "/runpod-volume/krea2-turbo",
  "free_gb": 506540.0
}
```

Check the fields, not just `ok`. `ok` only means the handler answered.

- `volume_mounted: false` → the network volume is not mounted. The worker falls back to the ~5 GB container
  disk and weight downloads will fail with `Errno 28`.
- `free_gb` must be comfortably above **22 GB**.
- `comfy_up: false` right after a cold boot is normal for a moment; persistent `false` means ComfyUI died.

`GET /health` is cheaper still — it reports queue and worker counts **without starting a GPU**. Always read it
first, and stop if `throttled > 0`.

### `generate` — prompt to PNG

Use async `/run` and poll `/status/{id}`. `/runsync` will time out on a cold start.

```bash
curl -s https://api.runpod.ai/v2/i3fvrhucaici89/run \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{
        "op":"generate",
        "prompt":"a rain-slick Dublin street at dusk, neon reflections, cinematic",
        "width":1280,
        "height":720,
        "steps":4
      }}'
```

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
        out = s["output"]
        open("out.png", "wb").write(base64.b64decode(out["png_b64"]))
        print(out["duration_ms"], "ms  $", out["estimated_usd"])
        break
    if s["status"] == "FAILED":
        print("failed:", s.get("error"))
        break
```

Never hardcode the API key. Read it from the environment.

#### Parameters

| Param | Type | Default | Notes |
| --- | --- | --- | --- |
| `prompt` | string | **required** | positive prompt; the negative prompt is always empty |
| `width` | int | `1280` | keep to multiples of 32 |
| `height` | int | `720` | keep to multiples of 32 |
| `steps` | int | `4` | Turbo is tuned for 4; raising it mostly buys GPU-seconds |
| `seed` | int | time-derived | pass a value for reproducibility |

#### Response

| Field | Meaning |
| --- | --- |
| `ok` | `true` on success; on failure `false` plus `error` as `TypeName: message` |
| `png_b64` | base64 PNG — this worker returns the image inline, it does not write to R2 |
| `duration_ms` | wall time inside the handler, including any weight download |
| `download_ms` | time spent fetching weights (`0` once the volume is warm) |
| `estimated_usd` | `duration_ms × usd_per_hour_assumed`; an estimate, not a RunPod invoice |
| `usd_per_hour_assumed` | from `RUNPOD_GPU_USD_PER_HR`, default `0.69` |
| `width` `height` `steps` `seed` | echoed back for the caller's ledger |

Errors are returned as a normal `200` body with `ok: false`, so the caller's poll loop never has to parse a
RunPod-level failure to see a model-level one.

---

## The ComfyUI graph

Built in `build_workflow()` and submitted to a local ComfyUI at `127.0.0.1:8188`.

```
UNETLoader(krea2_turbo_fp8_scaled, fp8_e4m3fn) ──────────────┐
                                                             ▼
CLIPLoader(qwen3vl_4b_fp8_scaled, type="krea2") ──► CLIPTextEncode(positive) ──► KSampler ──► VAEDecode ──► SaveImage
                                                └─► CLIPTextEncode(negative "") ─┘    ▲            ▲
EmptySD3LatentImage(width, height) ───────────────────────────────────────────────────┘            │
VAELoader(qwen_image_vae) ─────────────────────────────────────────────────────────────────────────┘

KSampler: steps=4, cfg=1.0, sampler=euler, scheduler=simple, denoise=1.0
```

Two details that are easy to get wrong:

- `CLIPLoader.type` is a **strict enum**. Krea is `krea2`. Guessing a plausible-looking value returns
  `value_not_in_list` from Comfy. Read `/object_info` or a known-good workflow instead of guessing.
- Krea-2-Turbo is a turbo model: **cfg 1.0**. Normal guidance values wash the image out.

---

## Weights on R2

Bucket `comfy`, prefix `comfy-models/krea2-turbo/` (~18 GB):

```
comfy-models/krea2-turbo/
  diffusion_models/krea2_turbo_fp8_scaled.safetensors
  text_encoders/qwen3vl_4b_fp8_scaled.safetensors
  vae/qwen_image_vae.safetensors
```

Lifecycle on boot:

1. If `/runpod-volume` is a **real mount** (`os.path.ismount`), the cache root is
   `/runpod-volume/krea2-turbo`. Otherwise it falls back to `ComfyUI/models` on the container disk — which is
   only ~5 GB and is wiped on scale-to-zero.
2. Each file is checked for a cached copy, then downloaded to a `.part` file and atomically renamed.
3. Files are symlinked into `ComfyUI/models/{diffusion_models,text_encoders,vae}` so Comfy can find them.
4. ComfyUI starts with `--highvram --disable-auto-launch`.
5. **Only then** does `runpod.serverless.start()` run.

Never re-download these from Hugging Face — they are already paid for and staged on R2. Never `COPY` a
`.safetensors` into the image, and never put `HF_TOKEN` in a layer.

---

## Build and test locally

```bash
docker build -t ms-runpod-krea:local .
```

The build clones ComfyUI at a pinned tag, strips torch/torchvision/torchaudio from Comfy's requirements (the
base image already has the right versions), and installs `runpod`, `boto3`, `requests`.

A local container has no GPU and no volume, so only the import path and `ping` are meaningful:

```bash
docker run --rm ms-runpod-krea:local \
  python /handler.py --test_input '{"input":{"op":"ping"}}'
```

Expect `volume_mounted: false` and a small `free_gb` locally. That is correct — it is exactly the signal the
worker is designed to surface.

---

## Deploy to RunPod

1. Push to `main`.
2. Create a GitHub **Release** — that is what triggers the RunPod rebuild.
3. Wait for the new image, then **purge the queue and stop old workers.** Running and paused workers keep
   serving the old image; FlashBoot resuming a paused worker will not pick up a new build or a newly attached
   volume.
4. Confirm the **worker id changed** before believing a fix landed.

### Endpoint settings

| Setting | Value | Why |
| --- | --- | --- |
| Network volume | EU-RO-1 | must hold ~18 GB of weights |
| Data centers | **EU-RO-1 only** | RunPod cannot mount a volume cross-datacenter, and it fails *silently* — workers sit in `Initializing` with no logs |
| GPU | 24 GB | fp8 Krea fits |
| Min / max workers | 0 / 1 | cost control; scale to zero between jobs |
| Idle timeout | 5s in production, 60s+ while iterating | a cold start pays ~90s of Triton JIT |
| FlashBoot | on | still recycle workers after any rebuild |
| Execution timeout | 600s | the first pull on a cold volume is slow |

Paste credentials into the endpoint's **Environment** tab. Nothing goes in git.

---

## Environment variables

Names only — see [`.env.example`](.env.example). Values belong on the RunPod endpoint, never in this repo.

| Name | Purpose |
| --- | --- |
| `ALLOW_GENERATE` | Keep `0` for the first console test so `ping` is all you can do. |
| `R2_ACCOUNT_ID` | used to derive the endpoint URL when `R2_ENDPOINT` is absent |
| `R2_ENDPOINT` | `https://<account-id>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY` / `R2_SECRET_KEY` | R2 S3-compatible credentials |
| `R2_BUCKET` | default `comfy`. `R2_BUCKET_NAME` is a higher-priority alias. |
| `RUNPOD_GPU_USD_PER_HR` | cost estimate basis, default `0.69` |
| `COMFY_DIR` | default `/workspace/ComfyUI` |
| `HF_TOKEN` | not needed at runtime — weights come from R2. Do not bake it into the image. |

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Workers stuck `Initializing`, no logs | volume is in a different datacenter than the GPU | pin endpoint data centers to the volume's DC only |
| `Errno 28` / `free_gb: 4.98` | `/runpod-volume` exists as an empty directory but is not a mount | attach a real network volume in the same DC, then **stop old workers** so a new one mounts it |
| `Failed to find C compiler` | Triton compiles kernels at runtime and the image lacks gcc | already fixed here: `gcc g++ build-essential` + `CC`/`CXX` |
| `infer_schema(...) unsupported type list[int]` | PyTorch 2.6 against ComfyUI 0.35.x | base image is pinned to PyTorch **2.7.0** — do not downgrade |
| `value_not_in_list — type` | wrong `CLIPLoader.type` | Krea is `krea2` |
| `throttled: 1` or `2` on health, jobs queued forever | account-level exponential backoff after repeated crashes. **Survives deleting the endpoint.** | fix the crash, purge the queue, wait 10–15 min. Never spam retries at a broken handler. |
| New build, same error, same worker id | old workers serving the old image | idle 5s, purge, stop them, verify a new worker id |
| First request ~100s with `download_ms: 39` | Comfy started inside the request | already fixed: init runs before `serverless.start()` |

The full write-ups — symptom, cause, fix, and what each one cost — are maintained in the application repo at
[`docs/RUNPOD.md`](https://github.com/farhann-saleem/sixeyes/blob/main/docs/RUNPOD.md). That file is
deliberately not summarised or thinned.

---

## Security

- No credentials in this repo. `.env.example` is names-only; `.gitignore` blocks `.env`, `*.pem`, `*.key`,
  `credentials.json`, `secrets.json` and `rclone.conf`.
- The Dockerfile copies **only `handler.py`**. Never `COPY .` — that is how a `.env` or a stray key ends up in
  a published layer.
- No weights, no `.safetensors`, no `.onnx` in git.
- Reads R2 with S3v4-signed requests using credentials supplied at runtime by the endpoint.
- Errors are returned as `TypeName: message` strings, which can include an R2 key or a path but never a
  credential.

---

## Known gaps

- The Dockerfile installs `runpod>=1.7.0,<2`. The house rule is **`runpod>=1.10.1,<2`**, because 1.7.11–1.10.0
  corrupts job tracking on network-volume endpoints. Worth tightening.
- Output is inline base64 rather than an R2 key, unlike the CPU worker. Fine for a single ~1 MP PNG; it would
  not scale to batches.
- No batch support — one image per job, `batch_size` is fixed at 1.
- `ALLOW_GENERATE` is documented and set in the environment but this handler does not gate on it; the CPU
  worker does. Generate is reachable whenever the endpoint is.
- No `RUNPOD_LESSONS.md` here — the canonical lessons file is the app repo's `docs/RUNPOD.md`.
