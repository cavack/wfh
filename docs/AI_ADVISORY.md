# AI Advisory

AI is optional and advisory only. It cannot create, veto, promote, or downgrade a canonical decision.

The maintained advisory path receives the canonical evidence packet, including derivatives/flow/cascade/cross-exchange context. Failure or missing credentials produces `UNAVAILABLE`; deterministic logic continues.

The canonical configured provider is Gemini when `GEMINI_API_KEY` is present. No local Ollama fallback is required by the current production architecture. An AI runtime/model must not be kept on the host unless active code references it and a maintained health path exists.

Never place credentials or raw provider responses containing secrets in logs, Git, or handoff certificates.
