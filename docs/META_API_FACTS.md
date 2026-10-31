# Meta Model API — documented and verified facts

Status legend: **DOC** = stated in official docs (fetched 2026-10-30) · **SRC** = read from the
`meta-sam-parser` 0.1.0 source · **LIVE** = confirmed by a real call from this repo · **UNVERIFIED** = assumption.

LIVE entries come from runs on 2026-10-31 (probe `runs/probe-20261031-133004.json`; scenarios
`runs/scenarios-20261031-13*`). 40 real calls (21 Muse, 19 SAM), est. total ≈ $0.20.

Docs are available as raw markdown: `https://dev.meta.ai/docs/<path>.md`; index `https://dev.meta.ai/llms.txt`.

## General
| Fact | Status |
|---|---|
| Base URL `https://api.meta.ai/v1`; auth `Authorization: Bearer $MODEL_API_KEY` | DOC |
| OpenAI SDK does not auto-read `MODEL_API_KEY`; pass explicitly | DOC |
| Protocols: Responses, Chat Completions (OpenAI-compatible), Messages (Anthropic-compatible) | DOC |
| Model IDs: `muse-spark-1.3` (also 1.2, 1.1, `-contributor` variants), `muse-wonder-1.0`, `sam-3.1` | DOC |
| Context window 1,048,576 tokens for Muse Spark/Wonder | DOC |
| Rate limits per team: `muse-spark-1.3` 3,000 RPM / 4M TPM; `sam-3.1` 3,000 RPM; contributor 150 RPM | DOC |
| Pricing (standard): Spark $1.25 in / $4.25 out / $0.15 cached per 1M tokens; SAM $2.50 per 1,000 images, $0.20 per 1,000 video frames (min 50 frames/request) | DOC |
| Contributor mode (`-contributor`) is far cheaper but **content may be used for training** — not used by default | DOC |
| Errors: `{"error":{code,message,param,type}}`; 429 has `Retry-After`; 500 "model output parsing failure" is retryable; 503 `service_overloaded`/`backend_unavailable` retry after `Retry-After`; 504: don't simply retry; 400/413 don't retry unchanged | DOC |
| 404 `model_not_found` also returned when team lacks model access | DOC |

## Muse Spark — image understanding
| Fact | Status |
|---|---|
| Chat Completions image part: `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}`, user role only | DOC |
| Responses image part: `{"type":"input_image","image_url":"<url or data URL>"}` or `file_id` | DOC |
| MIME: jpeg, png, gif, webp, x-icon; ≤ 50 MB inline; ≤ 50 images/request; undecodable → 400 | DOC |
| Response text at `choices[0].message.content`; `usage` has `prompt_tokens`, `completion_tokens` | DOC |
| ~1280px image ≈ 1,300–1,500 input tokens; exact count via `POST /v1/responses/input_tokens` | DOC |
| **Perception grounding:** positions on a normalized **0–1000** grid of the sent image, (0,0) top-left, x right, y down; coordinates relative to the image actually sent | DOC |
| Reasoning: Chat Completions top-level `reasoning_effort` (`minimal`…`max`); Responses `reasoning.effort`; `"none"` → 400 on Spark. Reasoning tokens are billed as output | DOC |

## Muse Spark — structured output
| Fact | Status |
|---|---|
| Chat Completions: `response_format={"type":"json_schema","json_schema":{"name":..., "schema":...}}`; constrained decoding | DOC |
| Responses API uses `text.format`; sending `response_format` there → 400 | DOC |
| Use `additionalProperties:false`, `required`, `enum`; recursive `$ref` → 400 | DOC |
| No `strict` flag documented | DOC |
| Non-recursive `$ref`/`$defs`, `anyOf` with null, numeric bounds: support not documented → we inline refs, use `anyOf[…,null]` for nullables, strip numeric/length keywords, and validate locally with Pydantic | UNVERIFIED (probe: `experiments/probe_api.py`) |

## SAM 3.1
| Fact | Status |
|---|---|
| `POST /v1/responses`, `model: "sam-3.1"`, one user message: `input_text` + `input_image` (`image_url`: URL or data URL) or `input_video` | DOC |
| Concept prompt = one short noun phrase; no multi-concept syntax (comma lists return 0); one request per concept; negation/spatial phrasing unreliable | DOC |
| Box/point prompts use the output token grammar (`<0f>1<|box;...;w=;h=|>`), cannot be combined with a phrase; ≤16 objects; `w`,`h` must equal media size (aspect mismatch → 400) | DOC |
| `stream: true` recommended; output arrives as `response.output_text.delta`, one line per frame; ends with `response.completed`. Non-streaming also supported | DOC |
| **Zero matches:** `response.completed` with empty output and **no** `output_text` events | DOC |
| `meta_sam_parser` raises `ResponsesStreamLaneError` on `response.completed` if no text lane was seen → we special-case zero matches before parsing | SRC |
| Line grammar: `<Nf>id<|box;x1;y1;x2;y2;w;h[;c]|><|mask;x=0;y=0[;c];data=H,W,<enc>payload|>`, records comma-separated; ids sparse, not 0-based-dense | DOC |
| Box coordinates are **source pixels, x2/y2 inclusive**; `w`,`h` = source size repeated on every record | DOC |
| Mask `data=H,W` is **height first**; encoding `~` lossless (default) / `!` one_bit (`metadata.mask_encoding`); payload is base85 | DOC |
| `metadata.include_confidence: "true"` (string) adds `c` in [0,1] to box and mask; needs `meta-sam-parser` ≥ 0.0.6 | DOC |
| Results can vary slightly between identical runs | DOC |
| Video: MP4/MOV H.264/H.265/MPEG-4; ≤ 15,000 frames; ≤ 16 tracked objects/frame; ids stable while object stays in frame (not across exit/occlusion) | DOC |

## meta-sam-parser (Python) 0.1.0
| Fact | Status |
|---|---|
| `pip install meta-sam-parser`, import `meta_sam_parser`, Python ≥ 3.10, no deps | DOC |
| Entry point (undocumented name in docs): `parse_responses_stream(async_iterable_of_events, image_segmentation_format())` → `await parsed.final_result()` (**a method** in Python, a property in TS) | SRC |
| Events may be plain dicts; output-text events need `item_id`, `output_index`, `content_index` | SRC |
| Records: `SegmentationBoxRecord(object_id, left, top, right, bottom, confidence)` — **half-open** (right = x2+1); `SegmentationMaskRecord(mask, bounds, confidence)`; mask raster covers `bounds` | SRC |
| `decode_mask_to_raster(mask)` → row-major bytes of 0/1, length W×H | DOC/SRC |
| Parser does not expose the wire `w`/`h`; we regex them from `raw_output` and discard geometry if they differ from the sent image size | SRC |

## LIVE results (2026-10-31)
| Fact | Status |
|---|---|
| Bearer auth with `MODEL_API_KEY`, base URL, `muse-spark-1.3` and `sam-3.1` all work for this account | LIVE |
| Chat Completions + `image_url` data URL (PNG→JPEG normalized) + `response_format` json_schema works; our 3.8 KB schema (inlined refs, `anyOf` null, enums, `additionalProperties:false`) accepted; output validated first time in all 20 structured Muse calls (no repair needed) | LIVE |
| `usage` returns `prompt_tokens`, `completion_tokens`, `completion_tokens_details.reasoning_tokens`, `prompt_tokens_details.cached_tokens` | LIVE |
| Hidden reasoning dominates output: e.g. 930 of 977 completion tokens on a tiny image call; 1,100–3,300 completion tokens per observation at default effort | LIVE |
| Default effort latency: Muse observe 8.2–44.1 s (median ~16 s), plan 6.7–9.2 s; `reasoning_effort:"low"`: observe 4.5–19.2 s, plan 2.8–4.4 s; per-photo wall 25–48 s (default) vs 6–29 s (low) | LIVE |
| SAM 3.1 streaming works; latency 0.8–8.1 s per concept (typ. 1.3–4 s); requests for different concepts run concurrently | LIVE |
| SAM `w`/`h` echoed equal to the normalized image size we sent (395×236, 1085×606, 282×198, …) | LIVE |
| SAM mask raster H×W equalled the inclusive box size in every observed record (e.g. box 267..394 × 111..172 → `data=62,128`) | LIVE |
| Zero-match case (e.g. "blue ethernet cable" on a photo with no cable) returned an empty result through our special-case path, no error | LIVE |
| Confidence `c` present with `include_confidence:"true"`; observed 0.64–0.96 | LIVE |
| `response.completed` `usage` for SAM is null/absent | LIVE |
| SAM "router" masks include antennas → box IoU vs Muse's body-only box can be low (0.32) even when both are right | LIVE |
| Muse 0–1000 boxes: good at device scale (IoU 0.75–0.95 vs SAM); at port scale can be offset by ~one port width | LIVE |
| Muse claims vary run to run (e.g. cable "beige" vs "off-white"; `fully_traced` vs `partially_visible`; label `illegible` vs `no_label`) | LIVE |

## Open questions (remaining)
1. Same-device multi-view behaviour on real captures (not yet tested).
2. Whether a SAM port concept (e.g. "ethernet port") gives precise port boxes to replace Muse port boxes.
3. Run-to-run stability rates (needs repeated runs per image).

## Original open questions (now answered above)
1. Does `response_format` accept our schema (inlined, `anyOf` nullables, ~3.8 KB)? (`probe_api.py`)
2. Real latency of Muse observation and SAM per image at 1600px.
3. Does SAM's mask raster ever differ from its box size (we handle it either way)?
4. How reliably does Muse read small port labels and report plug colour?
5. Do SAM `"blue ethernet cable"` masks reach into the plug/port region (needed for grounding corroboration)?
