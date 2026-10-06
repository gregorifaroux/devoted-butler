# Live heartbeat: how the chat keeps moving while workers churn

## The problem

smolagents' default `GradioUI._stream_response` is a single generator that loops over `agent.run(..., stream=True)` and `yield`s a chat snapshot each time an event arrives. When the Devoted Butler manager launches a code block that runs three managed workers back-to-back, that generator sits inside `agent.run()` for 100+ seconds with no event to emit, so the UI shows the "typing" dots and nothing else. The managed agents' inner steps are not bubbled up by smolagents.

`ButlerGradioUI._stream_response` fixes that in three parts.

## 1. Run the agent in a background thread, feed a queue

```python
def run_agent():
    for event in self.agent.run(task, stream=True, ...):
        q.put(("event", event))
    q.put(("done", None))

threading.Thread(target=run_agent, daemon=True).start()
```

The generator no longer blocks on `agent.run()`. It blocks on `q.get(timeout=1.0)` instead, which releases every second even when nothing has happened. That is the only way to get a periodic tick while the Python executor is running synchronously.

## 2. Attach `step_callbacks` to every worker

smolagents has a built-in hook that fires after each agent step completes. The override registers one callback per managed agent:

```python
def make_progress_cb(agent_name):
    def cb(step, agent=None):
        q.put(("progress", agent_name, f"step {step.step_number} done"))
    return cb

for sub in self._managed_agents():
    sub.step_callbacks.register(ActionStep, make_progress_cb(sub.name))
```

Now when `trend_agent` finishes an inner web-search step inside the pool thread, it pushes `("progress", "trend_agent", "step 2 done")` into the same queue.

Step callbacks only fire **after** a step completes. During a worker's first LLM call (which can be 30s+ on a local 14B model) they'd stay silent — the heartbeat would show "waiting" for ages. To fix that, `plan_party_in_parallel` also pings the queue directly through a `PROGRESS_SINK` the UI installs for the duration of the chat turn:

```python
PROGRESS_SINK = None  # module-level

@tool
def plan_party_in_parallel(brief):
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
        ...
```

The UI sets `PROGRESS_SINK = lambda name, info: q.put(("progress", name, info))` on entry and clears it in `finally`. This gives four states per worker: `waiting` → `running...` → `step N done` (one per inner LLM step) → `done`.

## 3. Interleave three message types in one generator

The main loop pulls items from the queue:

- `("event", event)` - a real smolagents event (step done, token delta, final answer). Converted to a `gr.ChatMessage` the same way the upstream UI does it (reusing `pull_messages_from_step` and `agglomerate_stream_deltas`), appended to `all_messages`, yielded.
- `("progress", name, info)` - either a step-callback ping or a `PROGRESS_SINK` ping. Updates `worker_status[name]`, refreshes the sticky "Working..." message, yields.
- `queue.Empty` - timeout, no events for 1 second. Refreshes the sticky message with the new elapsed time, yields. This is the ticking clock.
- `("done", None)` / `("error", msg)` - strips the sticky message and exits.

The sticky message is a `gr.ChatMessage` with `metadata={"status": "pending", "title": "Working..."}`. Gradio renders that as a collapsible spinner block. Its content is one line per managed agent built from `worker_status`:

```
- song_agent: step 1 done
- food_agent: done
- trend_agent: running...

_37s elapsed_
```

It lives at a fixed `heartbeat_idx` in `all_messages` so each refresh overwrites it in place rather than appending a new line. When a real step event arrives, the heartbeat is dropped (`drop_heartbeat`), the event is appended, and the heartbeat is re-created on the next idle tick.

## Why yield the whole list

Gradio's `ChatInterface` in streaming mode expects each yield to be the full current state of the conversation turn. Returning the whole `all_messages` list is how the frontend knows to repaint the chat with the heartbeat updated.

## Cleanup

The `finally` block clears `PROGRESS_SINK` and de-registers the step callbacks so repeated chats don't stack dozens of listeners on the same agents.

## One-line summary

One thread does the real work, one queue carries events + progress pings + idle ticks, one sticky message with one line per worker gives the user something that visibly moves.
