# Experiment: local Apertus 4B on a 4 GB laptop GPU (not part of the running system)

**This is not the model CLAUDE.md pins.** The pipeline pins `swiss-ai/Apertus-v1.5-8B`. This laptop has an
NVIDIA GTX 1650 Max-Q with 4 GB VRAM, which cannot hold an 8B model, so this setup serves
`swiss-ai/Apertus-v1.1-4B-Instruct` (Apache-2.0, not gated, revision `0d004ae50a03fda815ff7a091a89ab0baec94f3d`)
quantised to Q4_K_M. Results from it are **not comparable** with the 8B model. Do not mix its cache or
predictions with 8B runs.

Everything lives in `~/llm/` (a folder outside the repo). Nothing here goes into git. No secrets are needed
(the model is not gated, so no `HF_TOKEN`).

## 1. llama.cpp binaries (prebuilt, CUDA 12.4, release b11541)

Download from https://github.com/ggml-org/llama.cpp/releases/tag/b11541 and verify the SHA-256 shown there:

- `llama-b11541-bin-win-cuda-12.4-x64.zip`
- `cudart-llama-bin-win-cuda-12.4-x64.zip`

Unzip **both into the same folder**, `~/llm/llama.cpp/`.

## 2. Weights and conversion (official weights, converted locally)

```bash
cd ~/llm
python -m venv venv                                   # separate venv, NOT the repo .venv
./venv/Scripts/python -m pip install huggingface_hub
# source of convert_hf_to_gguf.py, same tag as the binaries:
#   https://github.com/ggml-org/llama.cpp/archive/refs/tags/b11541.zip  -> llama.cpp-b11541/
./venv/Scripts/python -m pip install -r llama.cpp-b11541/requirements/requirements-convert_hf_to_gguf.txt

./venv/Scripts/python -c "from huggingface_hub import snapshot_download; snapshot_download('swiss-ai/Apertus-v1.1-4B-Instruct', revision='0d004ae50a03fda815ff7a091a89ab0baec94f3d', local_dir='Apertus-v1.1-4B-Instruct')"

./venv/Scripts/python llama.cpp-b11541/convert_hf_to_gguf.py Apertus-v1.1-4B-Instruct --outtype bf16 --outfile Apertus-v1.1-4B-Instruct-bf16.gguf
./llama.cpp/llama-quantize.exe Apertus-v1.1-4B-Instruct-bf16.gguf Apertus-v1.1-4B-Instruct-Q4_K_M.gguf Q4_K_M
```

Sizes: weights 7.7 GB, bf16 GGUF 7.66 GB, Q4_K_M GGUF 2.43 GB. The bf16 GGUF can be deleted afterwards.

## 3. Run the server (127.0.0.1 only)

```bash
cd ~/llm
./llama.cpp/llama-server.exe -m Apertus-v1.1-4B-Instruct-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8000 -c 8192 -ngl all \
  --reasoning-budget 0 --temp 0 --alias apertus-v1.1-4b-instruct
```

- Never use `--host 0.0.0.0`. Check with `netstat -ano | grep ":8000 "`: it must show `127.0.0.1:8000`.
- Thinking is off: `--reasoning-budget 0`, and the model's chat template defaults to `Deliberation: disabled`.
- Send `temperature: 0` in each request as well. Temperature 0 is not a determinism guarantee (see CLAUDE.md).
- Stop it before the ASR bake-off if VRAM is tight (Ctrl+C in its terminal, or end the `llama-server.exe` process).

## 4. Verify

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/v1/models
```

Send the chat request from Python or a UTF-8 file. A Swiss German string pasted inline into `curl` in the
Windows shell is mangled and the server answers `400 ill-formed UTF-8`.

Env for the pipeline: `LLM_BASE_URL=http://127.0.0.1:8000/v1`, `LLM_MODEL=apertus-v1.1-4b-instruct`.

## Measured on this laptop (2026-10-10)

| What | Value |
|---|---|
| GPU | NVIDIA GeForce GTX 1650 with Max-Q Design, 4096 MiB |
| VRAM used with the model loaded | about 2990 MiB of 4096 MiB |
| Generation speed | 38.9 tokens/s (one request, 55 tokens) |
| Prompt speed | 1.6 tokens/s on the first request only (includes CUDA warm-up; not a steady-state figure) |
| Context | `-c 8192` accepted, but the model's training context is **4096**; llama.cpp warns about possible overflow. Use windows of at most 4096 tokens. |

Single request, so treat these numbers as indicative only.

## Findings from smoke tests (2026-10-10, indicative only)

Scratch tests, not part of the repo: one MOCK transcript (`fixtures/call_MOCK_001`), two quick prompts, one
quantisation (Q4_K_M). The expected facts come from the invented MOCK trace. This is not an accuracy metric.

- **`pipeline/llm.py` works against this server.** `probe()` resolves the model, and the `json_schema`
  response format is accepted (the output was valid JSON).
- **Temperature 0 was not deterministic here; the server's prompt cache was the cause.** Three identical
  requests with `cache_prompt: true` (the default) gave two different outputs (966 vs 2227 characters).
  With `"cache_prompt": false` all three were identical. `pipeline/llm.py` does not send this field today.
  Only 3 runs of one prompt, so confirm before relying on it. The project's own LLM cache stays the
  determinism guarantee (CLAUDE.md).
- **The 4B Q4_K_M model is too weak for fact extraction with these prompts.**
  - Prompt 1 (whole call, several segment ids per fact): 1 fact. It missed the advisor's request (s011) and
    the warning (s003), labelled the customer's disclosure (s012) as `request`, and cited 13 segments of both
    speakers.
  - Prompt 2 (one fact per segment, worked example): 5 facts, 3 failing the evidence checks. Two of them were
    copied from the example and do not occur in the call. It missed s011, s012 and s003 again.
  - Not tried: Q6_K, one request per segment, the pinned 8B model.
- Generation took 5-9 s (prompt 1) and 13-22 s (prompt 2) per whole-call request.

### Q6_K (3.15 GB), same two prompts

Made from the bf16 GGUF: `./llama.cpp/llama-quantize.exe Apertus-v1.1-4B-Instruct-bf16.gguf Apertus-v1.1-4B-Instruct-Q6_K.gguf Q6_K`.
It fits: server started with `-c 4096 -np 1 -ngl all` uses about 3200 MiB of 4096 MiB VRAM
(the `-c 8192` / 4 slots setup above was for Q4_K_M).

- Better than Q4_K_M: no facts copied from the worked example, and one fact is fully correct (the customer's
  disclosure in s012 with the right act and quote under prompt 1).
- Still not usable for extraction: it misses the advisor's request in s011 and the warning in s003 in both prompts, and it
  attributes correct quotes to the wrong segment ids (prompt 1: the s011 request cited as `s005, s012`;
  prompt 2: the same words cited as `s010`). The evidence validator would drop those facts.
- Prompt 1 gave identical output in 3 runs even with the default `cache_prompt`; prompt 2 differed with
  `cache_prompt: true` (659 vs 402 characters) and was identical with `false`. So the cache effect is real but not
  consistent. Still only 3 runs per setting.
- 4-10 s per whole-call request.

### Why the pinned Apertus v1.5 8B does not run on this laptop

- **VRAM.** An 8B model needs about 5 GB even at Q4, plus context. The laptop GPU has 4 GB.
- **llama.cpp cannot convert it (b11541).** `swiss-ai/Apertus-v1.5-8B` declares the architecture
  `Apertus1p5ForConditionalGeneration` (multimodal, with vision and audio tokenizers). llama.cpp's converter
  registers only `ApertusForCausalLM`, the architecture of the 4B, and `Apertus1p5` appears nowhere in its source.
- **No simple workaround.** The text layers use the prefix `model.language_model.layers.N...` (4B:
  `model.layers.N...`), the settings sit under `text_config`, and the embedding matrix has 266752 rows against a
  131072-token text vocabulary. A hand-made conversion would be unofficial and could not be checked without vLLM.
- **The intended route** is vLLM (swiss-ai image) on a GPU with 20 GB or more.
