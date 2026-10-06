"""Devoted Butler: a multi-agent party planner behind a Gradio chat UI.

A CodeAgent manager delegates to a song_agent (iTunes-backed) and a food_agent
(hardcoded menus). ButlerGradioUI subclasses smolagents.GradioUI to add a
placeholder, a soft theme, a local avatar, and a title.
"""
from smolagents import CodeAgent, ToolCallingAgent, GradioUI, LiteLLMModel, tool
import gradio as gr
import requests


PLACEHOLDER = (
    "### 🎩 Devoted Butler\n"
    "Describe your party and I'll coordinate songs and a menu for you.\n\n"
    "- Give me a theme (for example 'villain masquerade')\n"
    "- Tell me the venue (for example 'Wayne's mansion')\n"
    "- Ask for both songs and a menu, or just one\n\n"
    "_Example:_ Plan a villain masquerade party at Wayne's mansion."
)


class ButlerGradioUI(GradioUI):
    """GradioUI with a placeholder prompt, soft theme, and matching title."""

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
    instructions=(
        "Only suggest food and drinks. Call the tool and print the result, "
        "then give the final answer in a later step with ONE string."
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
song_agent.prompt_templates["managed_agent"]["task"] = SONG_TASK
food_agent.prompt_templates["managed_agent"]["task"] = FOOD_TASK

manager = CodeAgent(
    name="devoted_butler",
    description="Devoted Butler. Help plan your party... music, food, you name it.",
    tools=[],
    model=model,
    managed_agents=[song_agent, food_agent],
    max_steps=4,
    executor_kwargs={"timeout_seconds": 300},
    instructions=(
        "You are a coordinator. Do not do the workers' jobs. In ONE code block, call both workers, "
        "store each result in a variable, and print both:\n"
        "song_result = song_agent(task='...')\n"
        "food_result = food_agent(task='...')\n"
        "print(song_result)\nprint(food_result)\n"
        "In the next step, call final_answer(f'Songs:\\n{song_result}\\nMenu:\\n{food_result}') "
        "so the plan contains the workers' own text."
    ),
)


if __name__ == "__main__":
    ButlerGradioUI(manager).launch(share=False)
