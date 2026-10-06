"""Devoted Butler: a multi-agent party planner behind a Gradio chat UI.

A CodeAgent manager delegates to a song_agent (iTunes-backed) and a food_agent
(hardcoded menus). ButlerGradioUI subclasses smolagents.GradioUI to add a
placeholder, a soft theme, a local avatar, and a title.
"""
from smolagents import (
    CodeAgent,
    ToolCallingAgent,
    GradioUI,
    LiteLLMModel,
    DuckDuckGoSearchTool,
    VisitWebpageTool,
    tool,
)
from smolagents.memory import ActionStep, PlanningStep, FinalAnswerStep
from smolagents.models import ChatMessageStreamDelta, agglomerate_stream_deltas
from smolagents.gradio_ui import pull_messages_from_step
import gradio as gr
import requests
import threading
import queue
import time


PLACEHOLDER = (
    "### 🎩 Devoted Butler\n"
    "Describe your party and I'll coordinate songs and a menu for you.\n\n"
    "- Give me a theme (for example 'villain masquerade')\n"
    "- Tell me the venue (for example 'Wayne's mansion')\n"
    "- Ask for both songs and a menu, or just one\n\n"
    "_Example:_ Plan a villain masquerade party at Wayne's mansion."
)


class ButlerGradioUI(GradioUI):
    """GradioUI with a placeholder prompt, soft theme, matching title, and a
    live heartbeat that keeps the chat moving while workers churn.
    """

    def _managed_agents(self):
        return list(getattr(self.agent, "managed_agents", {}).values())

    def _stream_response(self, message, history):  # noqa: ARG002
        global PROGRESS_SINK
        task, task_files = self._process_message(message)

        q: queue.Queue = queue.Queue()
        workers = self._managed_agents()
        worker_names = [w.name for w in workers]

        def make_progress_cb(agent_name):
            def cb(step, agent=None):
                step_no = getattr(step, "step_number", "?")
                q.put(("progress", agent_name, f"step {step_no} done"))
            return cb

        registered = []
        for sub in workers:
            cb = make_progress_cb(sub.name)
            sub.step_callbacks.register(ActionStep, cb)
            registered.append((sub, cb))

        PROGRESS_SINK = lambda name, info: q.put(("progress", name, info))

        def run_agent():
            try:
                for event in self.agent.run(
                    task,
                    images=task_files,
                    stream=True,
                    reset=self.reset_agent_memory,
                    additional_args=None,
                ):
                    q.put(("event", event))
            except Exception as e:
                q.put(("error", repr(e)))
            finally:
                q.put(("done", None))

        threading.Thread(target=run_agent, daemon=True).start()

        all_messages: list = []
        accumulated_events: list = []
        streaming_msg_idx = None
        heartbeat_idx = None
        worker_status = {name: "waiting" for name in worker_names}
        start = time.time()
        skip_model_outputs = getattr(self.agent, "stream_outputs", False)

        def heartbeat_msg():
            elapsed = int(time.time() - start)
            lines = [f"- {name}: {worker_status[name]}" for name in worker_names]
            content = "\n".join(lines) + f"\n\n_{elapsed}s elapsed_"
            return gr.ChatMessage(
                role="assistant",
                content=content,
                metadata={"status": "pending", "title": "Working..."},
            )

        def ensure_heartbeat():
            nonlocal heartbeat_idx
            if heartbeat_idx is None:
                heartbeat_idx = len(all_messages)
                all_messages.append(heartbeat_msg())
            else:
                all_messages[heartbeat_idx] = heartbeat_msg()

        def drop_heartbeat():
            nonlocal heartbeat_idx
            if heartbeat_idx is not None:
                all_messages.pop(heartbeat_idx)
                heartbeat_idx = None

        try:
            while True:
                try:
                    item = q.get(timeout=1.0)
                except queue.Empty:
                    ensure_heartbeat()
                    yield all_messages
                    continue

                kind = item[0]

                if kind == "done":
                    drop_heartbeat()
                    yield all_messages
                    return
                if kind == "error":
                    drop_heartbeat()
                    all_messages.append(
                        gr.ChatMessage(role="assistant", content=f"Error: {item[1]}")
                    )
                    yield all_messages
                    return
                if kind == "progress":
                    _, agent_name, info = item
                    worker_status[agent_name] = info
                    ensure_heartbeat()
                    yield all_messages
                    continue

                event = item[1]
                if isinstance(event, (ActionStep, PlanningStep, FinalAnswerStep)):
                    drop_heartbeat()
                    if streaming_msg_idx is not None:
                        all_messages.pop(streaming_msg_idx)
                        streaming_msg_idx = None
                    for msg in pull_messages_from_step(
                        event, skip_model_outputs=skip_model_outputs
                    ):
                        all_messages.append(
                            gr.ChatMessage(
                                role=msg.role, content=msg.content, metadata=msg.metadata
                            )
                        )
                        yield all_messages
                    accumulated_events = []
                elif isinstance(event, ChatMessageStreamDelta):
                    drop_heartbeat()
                    accumulated_events.append(event)
                    text = agglomerate_stream_deltas(accumulated_events).render_as_markdown()
                    text = text.replace("<", r"\<").replace(">", r"\>")
                    msg = gr.ChatMessage(role="assistant", content=text)
                    if streaming_msg_idx is None:
                        streaming_msg_idx = len(all_messages)
                        all_messages.append(msg)
                    else:
                        all_messages[streaming_msg_idx] = msg
                    yield all_messages
        finally:
            PROGRESS_SINK = None
            for sub, cb in registered:
                try:
                    sub.step_callbacks._callbacks.get(ActionStep, []).remove(cb)
                except ValueError:
                    pass

    def create_app(self):
        type_messages_kwarg = {"type": "messages"} if gr.__version__.startswith("5") else {}
        chatbot = gr.Chatbot(
            label="Devoted Butler",
            placeholder=PLACEHOLDER,
            avatar_images=(None, "images/butler.png"),
            latex_delimiters=[
                {"left": r"$$", "right": r"$$", "display": True},
                {"left": r"$", "right": r"$", "display": False},
                {"left": r"\[", "right": r"\]", "display": True},
                {"left": r"\(", "right": r"\)", "display": False},
            ],
            scale=1,
            **type_messages_kwarg,
        )
        css = """
        .avatar-container img {
            object-fit: cover !important;
            width: 100% !important;
            height: 100% !important;
            padding: 0 !important;
        }
        """
        with gr.Blocks(theme="soft", css=css) as demo:
            gr.ChatInterface(
                fn=self._stream_response,
                chatbot=chatbot,
                title="Devoted Butler",
                multimodal=self.file_upload_folder is not None,
                save_history=True,
                **type_messages_kwarg,
            )
        return demo


model = LiteLLMModel(
    model_id="ollama_chat/qwen2.5:14b",
    api_base="http://127.0.0.1:11434",
    num_ctx=16384,
    temperature=0.2,
)


@tool
def suggest_food_menu(occasion: str) -> str:
    """Suggests FOOD and drinks for a party. Returns no music.
    Args:
        occasion: One of 'casual', 'formal', or 'superhero'. Pick the closest match.
    """
    occasion = occasion.lower()
    if "casual" in occasion:
        return "{menu: 'Pizza, snacks, and drinks.'}"
    elif "formal" in occasion or "masquerade" in occasion:
        return "{menu: '3-course dinner with wine and dessert.'}"
    elif "superhero" in occasion:
        return "{menu: 'Buffet with high-energy and healthy food.'}"
    return "{menu: 'Unknown occasion. Valid options: casual, formal, superhero.'}"


@tool
def find_songs(artists: str) -> str:
    """Finds one real song per artist in the iTunes catalog.
    Call this ONCE with ALL artists in a single string.
    Args:
        artists: Artist names separated by commas. Example: 'Madonna, Iron Maiden, Ozzy Osbourne, Queen, Ice-T'
    """
    lines = []
    for name in (a.strip() for a in artists.split(",")):
        r = requests.get("https://itunes.apple.com/search", params={"term": name, "entity": "song", "limit": 5}, timeout=10)
        hits = [t for t in r.json().get("results", []) if name.lower() in t["artistName"].lower()]
        lines.append(f"{hits[0]['trackName']} - {hits[0]['artistName']}" if hits else f"No song found for {name}")
    return "\n".join(lines)


song_agent = ToolCallingAgent(
    name="song_agent",
    description="Finds songs and artists for a party. Give it a party theme and a venue.",
    tools=[find_songs],
    model=model,
    max_steps=8,
    stream_outputs=True,
    instructions=(
        "Name 5 artists whose music fits the theme, then call find_songs once per artist, "
        "for example find_songs('Billie Eilish'). Keep only songs whose artist is the one you searched. "
        "If a search returns nothing, change the keyword. "
        "Never list a song that find_songs did not return."
    ),
)

food_agent = ToolCallingAgent(
    name="food_agent",
    description="Suggests food and drinks for a party. Give it the type of party.",
    tools=[suggest_food_menu],
    model=model,
    max_steps=3,
    stream_outputs=True,
    instructions=(
        "Only suggest food and drinks. Call the tool and print the result, "
        "then give the final answer in a later step with ONE string."
    ),
)

trend_agent = ToolCallingAgent(
    name="trend_agent",
    description=(
        "Agentic RAG. Searches the live web for party-trend ideas tailored to a theme "
        "and returns themed food, music, and setting/decor suggestions. "
        "Give it the party theme (and venue if known)."
    ),
    tools=[DuckDuckGoSearchTool()],
    model=model,
    max_steps=4,
    stream_outputs=True,
    instructions=(
        "RULES:\n"
        "- Make EXACTLY ONE tool call per reply. Never batch multiple tool calls.\n"
        "- Never invent tool call ids like 'broad_search' or 'synthesize'.\n\n"
        "STEP 1: call web_search once. Query = '<theme> party ideas food music decor'.\n"
        "STEP 2: call final_answer with ONE Markdown STRING (not a dict, not JSON). The string must "
        "match this exact shape:\n"
        "### Food ideas\n- bullet\n- bullet\n- bullet\n\n"
        "### Music & vibe\n- bullet\n- bullet\n- bullet\n\n"
        "### Setting & decor\n- bullet\n- bullet\n- bullet\n\n"
        "Pull concrete, themed items from the search snippets. No URLs. No preamble."
    ),
)

SONG_TASK = (
    "You are '{{name}}'. Your manager gave you this task:\n{{task}}\n\n"
    "Pick 5 artists whose music fits the task. Then call find_songs ONCE with all five names "
    "in one string, for example find_songs('Madonna, Iron Maiden, Ozzy Osbourne, Queen, Ice-T'). "
    "Your last step must be a call to the tool final_answer, with the lines find_songs returned "
    "as its answer argument. Do not write the songs as plain text. "
    "Every reply must be a tool call."
)
FOOD_TASK = (
    "You are '{{name}}'. Your manager gave you this task:\n{{task}}\n\n"
    "Call suggest_food_menu once. Then call final_answer with ONE string containing "
    "exactly the text the tool returned. Add nothing."
)
TREND_TASK = (
    "You are '{{name}}'. Your manager gave you this task:\n{{task}}\n\n"
    "Reply 1: ONE tool call to web_search with '<theme> party ideas food music decor'.\n"
    "Reply 2: ONE tool call to final_answer. The answer argument must be a single Markdown "
    "STRING (not a dict, not JSON) with exactly these three ### headers:\n"
    "### Food ideas\n### Music & vibe\n### Setting & decor\n"
    "Each section has 2-4 '- ' bullets drawn from the search snippets. No URLs. No preamble. "
    "Every reply is exactly one tool call. Never batch tool calls."
)
song_agent.prompt_templates["managed_agent"]["task"] = SONG_TASK
food_agent.prompt_templates["managed_agent"]["task"] = FOOD_TASK
trend_agent.prompt_templates["managed_agent"]["task"] = TREND_TASK

for a in (song_agent, food_agent, trend_agent):
    a.prompt_templates["managed_agent"]["report"] = "{{final_answer}}"

PROGRESS_SINK = None


def _ping(agent_name, info):
    sink = PROGRESS_SINK
    if sink is not None:
        sink(agent_name, info)


@tool
def plan_party_in_parallel(brief: str) -> str:
    """Runs all three worker agents (song, food, trend) IN PARALLEL on the party brief
    and returns a single Markdown plan combining their outputs.
    Call this exactly once per party request; it is the only tool you need.
    Args:
        brief: The user's party brief, including the theme and any venue. Pass it verbatim.
    """
    from concurrent.futures import ThreadPoolExecutor

    def run(agent, name):
        _ping(name, "running...")
        try:
            result = agent(brief)
            _ping(name, "done")
            return result
        except Exception as e:
            _ping(name, f"error: {e!r}")
            raise

    with ThreadPoolExecutor(max_workers=3) as ex:
        s = ex.submit(run, song_agent, "song_agent")
        f = ex.submit(run, food_agent, "food_agent")
        t = ex.submit(run, trend_agent, "trend_agent")
        song_result, food_result, trend_result = s.result(), f.result(), t.result()
    return (
        f"## Songs\n{song_result}\n\n"
        f"## Menu\n{food_result}\n\n"
        f"{trend_result}"
    )


manager = CodeAgent(
    name="devoted_butler",
    description="Devoted Butler. Help plan your party... music, food, you name it.",
    tools=[plan_party_in_parallel],
    model=model,
    managed_agents=[song_agent, food_agent, trend_agent],
    max_steps=3,
    stream_outputs=True,
    executor_kwargs={"timeout_seconds": 300},
    instructions=(
        "Step 1: ONE code block that calls plan_party_in_parallel exactly once with the user's "
        "brief verbatim, stores the result, and prints it:\n"
        "plan = plan_party_in_parallel(brief='<the full user brief>')\n"
        "print(plan)\n"
        "Step 2: call final_answer(plan). Do not edit, reformat, or add anything to plan."
    ),
)


if __name__ == "__main__":
    ButlerGradioUI(manager).launch(share=False)
