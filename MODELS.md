# Models — Krea-2-Turbo

## Primary model

| | |
| --- | --- |
| Name | Krea-2-Turbo |
| Precision | fp8 scaled |
| Steps | **4** (default) |
| CFG | **1.0** |
| Sampler / scheduler | euler / simple |
| Typical size | 1280×720 (multiples of 32) |

## R2 layout

Bucket `comfy`, prefix `comfy-models/krea2-turbo/` (~18 GB):

```
comfy-models/krea2-turbo/
  diffusion_models/krea2_turbo_fp8_scaled.safetensors
  text_encoders/qwen3vl_4b_fp8_scaled.safetensors
  vae/qwen_image_vae.safetensors
```

Never re-download from Hugging Face at runtime. Never `COPY` `.safetensors` into the image.

## API parameters

| Param | Default | Notes |
| --- | --- | --- |
| `prompt` | required | positive only; negative always empty |
| `width` | 1280 | ×32 |
| `height` | 720 | ×32 |
| `steps` | 4 | raising mostly buys GPU-seconds |
| `seed` | time-derived | pass for reproducibility |

## Response fields

`ok`, `png_b64`, `duration_ms`, `download_ms`, `estimated_usd`, `usd_per_hour_assumed`, echoed geometry/steps/seed.

## Product UI

Surfaces as **Krea 2 Turbo** on the Images model strip. Not the default Avatar provider.
