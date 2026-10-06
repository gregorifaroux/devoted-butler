# devoted-butler

A multi-agent party planner behind a Gradio chat UI. A `CodeAgent` manager ("Devoted Butler") picks which of three `ToolCallingAgent` workers the brief actually needs: `song_agent` (iTunes-backed), `food_agent` (hardcoded menus), and `trend_agent` (agentic RAG over DuckDuckGo), then concatenates their output into one Markdown plan.

![Devoted Butler UI](images/butler_screenshot.png)

## Topology

- **Manager** — `CodeAgent`, no tools of its own. Reads each worker's `name` + `description` and picks which workers the brief calls for. One worker per code block, sequentially. Final step concatenates each worker's output under a `## <name>` header via `final_answer`.
- **song_agent** — `ToolCallingAgent` with `find_songs` only. Picks 5 artists that fit the theme, calls `find_songs` once with all names, returns the lines iTunes returned.
- **food_agent** — `ToolCallingAgent` with `suggest_food_menu` only. Calls the tool once and forwards its text as the final answer.
- **trend_agent** — `ToolCallingAgent` with `DuckDuckGoSearchTool`. Agentic RAG: searches live web results for ideas tailored to the theme, then synthesizes a Markdown block with `### Food ideas`, `### Music & vibe`, and `### Setting & decor` sections.

Each worker's `managed_agent` task template is overridden to constrain its reply shape (single tool-call per step, final answer must be a plain Markdown string). The `report` template is also overridden to `{{final_answer}}` so the worker's output isn't prefixed by "Here is the final answer from your managed agent 'X':".

## Language guard

`qwen2.5:14b` occasionally slips into Thai or Chinese mid-generation. Three safeguards:

1. `temperature=0.0` on `LiteLLMModel` for deterministic sampling.
2. An `ENGLISH_RULE` string ("You MUST write ALL text in English only.") prepended to each worker's `instructions` field — lands in the system prompt.
3. An `ENGLISH_TAIL` string appended to each worker's `managed_agent.task` template — the last thing the model sees before generating.

## UI

`ButlerGradioUI` subclasses `smolagents.GradioUI` to:

- Set a markdown `placeholder` so the empty chat shows instructions (theme, venue, example prompt) instead of a blank pane.
- Wrap `gr.ChatInterface` in `gr.Blocks(theme="soft", css=...)` for a cleaner look and force the avatar to fill the circle (`object-fit: cover`).
- Set the chatbot label and interface title to `"Devoted Butler"`.
- Point `avatar_images` at the local `images/butler.png`.
- Expose three one-click example prompts under the input: "Suggest party themes", "Songs for a punk rock party", "Menu for a formal dinner with co-workers".

smolagents requires an agent `name` to be a valid Python identifier, so the manager is `name="devoted_butler"` with the display name in `description`.

`ButlerGradioUI` also overrides `_stream_response` to show a live "Working..." heartbeat with elapsed seconds and one line per worker (`song_agent: idle`, `food_agent: step 1 done`, `trend_agent: step 2 done`) while the manager's code block is running. See [docs/streaming.md](docs/streaming.md) for how the thread + queue + step_callbacks interleave works.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [Ollama](https://ollama.com/) with `qwen2.5:14b` pulled:

```bash
ollama pull qwen2.5:14b
```

## Setup

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Run

```bash
./devoted_butler.sh
```

The script activates `.venv`, starts Ollama if it isn't running, then launches the UI. Gradio prints a local URL. Open it, click one of the example prompts or type a party brief (for example "Plan a villain masquerade party at Wayne's mansion"), and the manager decides which workers to invoke.

## Files

- `devoted_butler.py` — model, tools, workers, manager, `ButlerGradioUI`, Gradio launch.
- `devoted_butler.sh` — launcher.
- `docs/streaming.md` — how the live "Working..." heartbeat works.
- `images/butler.png` — chat avatar.
- `images/butler_screenshot.png` — UI screenshot shown above.
- `requirements.txt` — Python dependencies.
