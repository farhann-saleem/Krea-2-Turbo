# Architecture — Krea-2-Turbo

## Role

Text-to-image leg of Marketing Studio. The app’s default avatar path is OpenRouter FLUX.2 Klein; this worker is the self-hosted T2I path (Images desk / catalog).

## Boot sequence

1. If `/runpod-volume` is a **real mount** (`os.path.ismount`), cache root = `/runpod-volume/krea2-turbo`. Else fall back to container disk (~5 GB) — downloads will fail.
2. Ensure each weight file from R2 (`.part` + atomic rename).
3. Symlink into `ComfyUI/models/{diffusion_models,text_encoders,vae}`.
4. Start ComfyUI (`--highvram --disable-auto-launch`).
5. **Only then** call `runpod.serverless.start()`.

## Comfy graph

```
UNETLoader(krea2_turbo_fp8_scaled, fp8_e4m3fn) ──────────────┐
                                                             ▼
CLIPLoader(…, type="krea2") ──► CLIPTextEncode(pos) ──► KSampler ──► VAEDecode ──► SaveImage
                             └─► CLIPTextEncode(neg "") ─┘    ▲            ▲
EmptySD3LatentImage ─────────────────────────────────────────┘            │
VAELoader(qwen_image_vae) ────────────────────────────────────────────────┘

KSampler: steps=4, cfg=1.0, sampler=euler, scheduler=simple, denoise=1.0
```

Traps: `CLIPLoader.type` must be `krea2` (strict enum). Turbo wants **cfg 1.0**.

## I/O

- Input: JSON (`prompt`, optional `width`/`height`/`steps`/`seed`)
- Output: inline `png_b64` (not an R2 key) — fine for one ~1 MP PNG
- Errors: HTTP 200 body with `ok: false` + `error: TypeName: message`

## Security

Dockerfile copies **only `handler.py`**. No weights, no `.env`, no `COPY .`. Credentials only at runtime on the endpoint.
