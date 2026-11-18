# Using Ollama instead of Claude

The onthesignal AI assistant can use a model served by [Ollama](https://ollama.com) instead
of Claude: no API key, no cost per request, and the signal summaries stay on your network.
The recommended setup is **Qwen3.8 27B on an NVIDIA GB10** (128 GB of unified memory) reached
over the network, with onthesignal running on your PC. A small model on the PC itself also
works for simple requests (section 6).

| | Claude (`anthropic`) | Ollama on a GB10 (`ollama`) |
| --- | --- | --- |
| Where the model runs | Anthropic servers | the GB10, on your network |
| What is sent | summaries of signals and results, never the samples | the same, but it stays on your network |
| Key | `ANTHROPIC_API_KEY` | none |
| Context | 1M tokens | up to 256K tokens with Qwen3.8 (1M with vLLM, section 5) |

## 1. On the GB10: install Ollama and open it to the network

```bash
curl -fsSL https://ollama.com/install.sh | sh   # installs Ollama and a systemd service
sudo systemctl edit ollama
```

Add these lines in the editor and save:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_KEEP_ALIVE=1h"
Environment="OLLAMA_FLASH_ATTENTION=1"
```

- `OLLAMA_HOST=0.0.0.0` makes Ollama listen on the network (by default it only answers on
  the GB10 itself).
- `OLLAMA_KEEP_ALIVE=1h` keeps the model in memory for an hour after the last request.
  Without it, Ollama unloads it after 5 minutes and the next question waits while 30 GB are
  loaded again.
- Optional: `Environment="OLLAMA_KV_CACHE_TYPE=q8_0"` halves the memory used by the context
  (section 3), at the cost of a very small loss of precision.

```bash
sudo systemctl restart ollama
```

**Ollama has no authentication**: anyone who can reach port 11434 can use the models. Keep
the GB10 on a trusted network and restrict the port to your machines, for example
`sudo ufw allow from 192.168.1.0/24 to any port 11434 proto tcp`. Requests travel
unencrypted.

From your PC, check that the GB10 answers:

```bash
curl http://<gb10-address>:11434/api/tags      # lists the installed models (JSON)
```

## 2. Download Qwen3.8 27B (on the GB10)

```bash
ollama pull qwen3.8:27b-q8_0
```

Qwen3.8 supports tools (required: the assistant works by calling onthesignal functions such
as `lnm` or `noise`), thinking and images. Ollama offers these builds of the 27B model:

| Tag | Size | Notes |
| --- | --- | --- |
| `qwen3.8:27b-q8_0` | 30 GB | 8 bits, closest to FP8; **recommended on a GB10** |
| `qwen3.8:27b` (= `27b-q4_K_M`) | 18 GB | 4 bits, faster, slightly less accurate |
| `qwen3.8:27b-bf16` | 56 GB | full precision, slowest |

Ollama has **no FP8 build**. The `mxfp8` and `nvfp4` tags are MLX builds for Apple Silicon
and do not run on a GB10. The official FP8 weights (`Qwen/Qwen3.8-27B-FP8`) are served by vLLM
or SGLang (section 5).

Thinking is on by default: the model reasons before answering, which makes answers better on
multi-step requests but slower.

## 3. Context length

Every request starts with a fixed part, the system prompt and the description of the 24 tools,
of about **9 600 tokens**, followed by the conversation. Ollama's default context is often
**4096 tokens**. When the prompt is longer, Ollama **silently cuts it**: the model then sees
incomplete tool descriptions and calls them with wrong arguments (in our tests, `lnm(S="S1")`
instead of `lnm(signal="S1")`).

Set the context in onthesignal with `[ai] context` (section 4). onthesignal sends it to
Ollama (`num_ctx`) with every request, so the server does not need to be configured for it.

**The maximum is 262 144 tokens (256K) for Qwen3.8 in Ollama**, the length the model was
trained for. If you ask for more, Ollama silently uses 262 144; the only trace is a line in
the server log (`journalctl -u ollama` on the GB10):

```text
msg="requested context size too large for model" num_ctx=1000000 n_ctx_train=262144
```

Going to 1M tokens requires an extension of the positional encoding (YaRN) that Ollama does
not provide: see section 5.

Memory needed on the GB10 for `qwen3.8:27b-q8_0`:

| `context` | Model | Context (KV cache) | Total |
| --- | --- | --- | --- |
| 32 768 | 30 GB | 2 GB | about 32 GB |
| 262 144 | 30 GB | 16 GB (8 GB with `OLLAMA_KV_CACHE_TYPE=q8_0`) | about 46 GB |

The context memory is computed from the model architecture (16 full-attention layers, 4 KV
heads of dimension 256: 64 KiB per token at 16 bits). Ollama reserves it when the model is
loaded, whatever the length of the conversation. Both lines fit in the 128 GB of a GB10.
A conversation with the assistant rarely goes beyond a few tens of thousands of tokens, so
256K leaves a large margin; lower `context` if the GB10 needs the memory for something else.

After a first question, `ollama ps` on the GB10 shows the loaded model with its `CONTEXT`
(it must show the value you set) and `100% GPU` in the `PROCESSOR` column.

## 4. Configure onthesignal (on the PC)

In `onthesignal.toml` (in the folder where you start onthesignal), or in
`~/.config/onthesignal/config.toml` for every project:

```toml
[ai]
provider = "ollama"
model = "qwen3.8:27b-q8_0"                 # exact name from `ollama list` on the GB10
base_url = "http://<gb10-address>:11434"   # host name or IP address of the GB10
context = 262144                           # tokens; 0 = Ollama default (often too short)
```

In the console, `/model` shows the active configuration:

```text
AI provider: ollama (qwen3.8:27b-q8_0, http://<gb10-address>:11434, context 262144 tokens)
```

`/model ollama <model>` changes the model for the session; `base_url` and `context` still come
from the configuration file (or from `/config ai.context=65536` for the session). To switch
back to Claude: `/model anthropic claude-opus-5-5` (the key must be in `ANTHROPIC_API_KEY`).

Then use the assistant as usual: `/ai` to toggle the AI mode, or `/ai <question>` for a single
question.

## 5. FP8 and 1M tokens: vLLM instead of Ollama

The official FP8 build, `Qwen/Qwen3.8-27B-FP8`, is natively 262 144 tokens and can be extended
to 1 000 000 tokens with YaRN (factor 4) in vLLM or SGLang. vLLM exposes an OpenAI-compatible
API that onthesignal reaches through its `openai` provider:

```toml
[ai]
provider = "openai"
model = "Qwen/Qwen3.8-27B-FP8"                 # the name vLLM serves
base_url = "http://<gb10-address>:8000/v1"
```

The `openai` client needs `OPENAI_API_KEY` even for vLLM: `export OPENAI_API_KEY=none`, or the
key given to vLLM with `--api-key`. `context` is ignored by this provider; the context length
is set on the vLLM side (`--max-model-len`).

Start vLLM on the GB10 following the
[model card](https://huggingface.co/Qwen/Qwen3.8-27B-FP8) and the
[vLLM recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-27B). Two points matter for onthesignal:
tool calling must be enabled (`--enable-auto-tool-choice` and the tool parser the recipe gives
for Qwen3.8), and the 1M context needs the YaRN override and `--max-model-len 1000000` given
on the model card. The card warns that static YaRN can lower quality on short texts, which is
the usual case for the assistant: only enable 1M if you need it. The context then takes about
64 GB at 16 bits, on top of the weights.

This setup has not been tested with onthesignal yet.

## 6. Ollama on the PC itself (small models)

For simple requests without a GB10, run a small model locally. Measured on a PC with an NVIDIA
RTX A400 (4 GB), with the full onthesignal prompt and `context = 16384`
(request: "Compare S1 to the low noise model"):

| Model | Size | Time | Tool call |
| --- | --- | --- | --- |
| `qwen3.5:2b` | 2.7 GB | 20 s | `lnm(signal="S1", x="freq")` |
| `qwen3.5:0.8b` | 1.0 GB | 12 s | `lnm(signal="S1", smoothing=8, show_nhnm=False)` |

```bash
ollama pull qwen3.5:2b
```

```toml
[ai]
provider = "ollama"
model = "qwen3.5:2b"
base_url = ""          # empty = local server http://127.0.0.1:11434
context = 16384
```

`ollama ps` shows how the model is split: a CPU/GPU share such as `39%/61%` means it does not
fit in GPU memory and part of the work is done by the CPU, which is slower.

## 7. What the model receives and can do

The rules are the same as with Claude:

- the model receives the rules from `docs/ai/agent.md`, your `context.md`, the list of
  signals with their metadata, and the results of the analyses (values, warnings);
  **never the samples**;
- analyses run without confirmation (`[ai] auto_execute = "read_only"`; `"none"` asks every
  time); writing files, running scripts, acquiring and running Python code proposed by the
  model always ask for confirmation.

## 8. Troubleshooting

| Message or symptom | Cause and fix |
| --- | --- |
| `The 'ollama' package is not installed` | `pip install -e ".[ai]"` |
| `Failed to connect to Ollama` | wrong `base_url`, or the server is not running or not listening on the network: check `curl http://<gb10-address>:11434/api/tags`, `OLLAMA_HOST` (section 1) and the firewall |
| `model '…' not found (status code: 404)` | `ollama pull <model>` on the GB10; the name must match `ollama list` exactly, tag included |
| `No model configured for ollama` | set `model` in `[ai]` or use `/model ollama <model>` |
| `[ai] context must be a number of tokens` | `context = 262144` (an integer, without quotes or units) |
| `ollama ps` shows a smaller `CONTEXT` than requested | the model's maximum is lower (262 144 for Qwen3.8); see the server log |
| wrong argument names, invented functions, tools ignored | context too short (section 3), or a model without tool support or too small |
| the first answer after a pause is very slow | the model is being loaded again: set `OLLAMA_KEEP_ALIVE` (section 1) |
| the model answers in text instead of running the analysis | rephrase with the function name ("run lnm on S1") |
