# devoted-butler

A multi-agent party planner behind a Gradio chat UI. A `CodeAgent` manager ("Devoted Butler") delegates to two `ToolCallingAgent` workers: `song_agent` (iTunes-backed) and `food_agent` (hardcoded menus), then combines their output into one plan.

![Devoted Butler UI](images/butler_screenshot.png)

## Topology

- **Manager** — `CodeAgent`, no tools of its own. Reads each worker's `name` + `description` and hands them tasks via `managed_agents=[...]`. A single code block calls both workers, prints their results, then calls `final_answer` with the combined output.
- **song_agent** — `ToolCallingAgent` with `find_songs` only. Picks 5 artists that fit the theme, calls `find_songs` once with all names, returns the lines iTunes returned.
- **food_agent** — `ToolCallingAgent` with `suggest_food_menu` only. Calls the tool once and forwards its text as the final answer.

Each worker's `managed_agent` task template is overridden to constrain its reply shape (single tool-call per step, final answer must be the tool's own text).

## UI

`ButlerGradioUI` subclasses `smolagents.GradioUI` to:

- Set a markdown `placeholder` so the empty chat shows instructions (theme, venue, example prompt) instead of a blank pane.
- Wrap `gr.ChatInterface` in `gr.Blocks(theme="soft", css=...)` for a cleaner look and force the avatar to fill the circle (`object-fit: cover`).
- Set the chatbot label and interface title to `"Devoted Butler"`.
- Point `avatar_images` at the local `images/butler.png`.

smolagents requires an agent `name` to be a valid Python identifier, so the manager is `name="devoted_butler"` with the display name in `description`.

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

The script activates `.venv`, starts Ollama if it isn't running, then launches the UI. Gradio prints a local URL. Open it, type a party brief (for example "Plan a villain masquerade party at Wayne's mansion"), and the manager coordinates the two workers.

## Files

- `devoted_butler.py` — model, tools, workers, manager, `ButlerGradioUI`, Gradio launch.
- `devoted_butler.sh` — launcher.
- `images/butler.png` — chat avatar.
- `images/butler_screenshot.png` — UI screenshot shown above.
- `requirements.txt` — Python dependencies.
