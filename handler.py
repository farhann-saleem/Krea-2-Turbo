"""RunPod serverless handler — ping only until generate is wired.

Cheap rule: first console test MUST be {"input": {"op": "ping"}}.
Generate is refused unless ALLOW_GENERATE=1. Do not set that until
weights live on a network volume. Never return image bytes; return R2 keys later.
"""
import os
import runpod

WORKER = "krea"
ALLOW = os.environ.get("ALLOW_GENERATE", "0").strip().lower() in {"1", "true", "yes", "on"}


def handler(job):
    inp = job.get("input") or {}
    op = str(inp.get("op") or "ping").lower()
    if op == "ping":
        return {
            "ok": True,
            "worker": WORKER,
            "allow_generate": ALLOW,
            "hint": "Do not send generate until ALLOW_GENERATE=1 and a network volume holds the weights.",
        }
    if op in {"generate", "sample"}:
        if not ALLOW:
            return {
                "error": "ALLOW_GENERATE is off. Assignment mode — no model load, no Hugging Face pull."
            }
        return {"error": "generate is not wired yet. Weights must be on a network volume first."}
    return {"error": f"unknown op {op}. Use ping."}


runpod.serverless.start({"handler": handler})
