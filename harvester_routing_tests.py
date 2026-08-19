from app.interpretation import interpret_fragment


def candidates(text: str):
    return interpret_fragment(text)["candidates"]


def by_type(text: str, route_type: str):
    return [item for item in candidates(text) if item["type"] == route_type]


# Shopping is a Get List item, not a task, reminder, or Shitlist entry.
shopping = by_type("I just remembered I need to buy some carrots.", "get_list")
assert len(shopping) == 1 and shopping[0]["title"].lower() == "carrots"
assert not by_type("I just remembered I need to buy some carrots.", "shitlist")

# A dated actionable statement creates a reminder but never invents a clock time.
dated = by_type("Call Roger next Wednesday on his birthday.", "reminder")
assert len(dated) == 1 and "call roger" in dated[0]["title"].lower()
assert dated[0]["metadata"]["has_future_language"] is True

# Clear implied maintenance is routed as a repair/cleaning job.
headlight = by_type("Oh, the car headlight is out, gotta fix that.", "run_maintain")
assert len(headlight) == 1 and headlight[0]["title"] == "Fix car headlight"
windows = by_type("My office windows are so dirty.", "run_maintain")
assert len(windows) == 1 and windows[0]["title"] == "Clean office windows"

# A place-triggered reminder stays a location trigger, not an invented time.
vacuum = candidates("Bloody vacuum cleaner just notified an empty tank status. I'm out remind me when I get home.")
assert any(item["type"] == "run_maintain" for item in vacuum)
location_reminders = [item for item in vacuum if item["type"] == "reminder"]
assert location_reminders and location_reminders[0]["metadata"]["location_trigger"].lower() == "when i get home"

# Questions remain questions; reflections remain observations rather than new plans.
weather = candidates("Is it going to be nice weather at Rottnest on Friday?")
assert [item["type"] for item in weather] == ["ask_ai"]
reflection = interpret_fragment("I didn't train again today, I need a break.")
assert reflection["memory_class"] == "reference"
assert any(item["type"] == "daybook" for item in reflection["candidates"])
assert not any(item["type"] in {"run_maintain", "reminder", "shitlist"} for item in reflection["candidates"])

# Legacy wording is retained, even when it contains an end-of-life phrase.
legacy = interpret_fragment("My Dad never got to say goodbye. Lay me to rest in 13m. The wind and tide will carry me to them.")
assert legacy["memory_class"] == "permanent"
assert legacy["candidates"] == []

# Weekly Review is an agenda item, not an automatic plan change or Decision.
weekly = interpret_fragment("We really need to change this plan. It isn't working. Please bring it up in the weekly review.")
assert weekly["memory_class"] == "reference"
assert any(item["type"] == "weekly_review" for item in weekly["candidates"])
assert not any(item["type"] == "decision" for item in weekly["candidates"])

# Spoken corrections produce the final intended item while original words remain in the draft.
correction = interpret_fragment("Get carrots — actually make that potatoes.")
assert correction["original_text"] == "Get carrots — actually make that potatoes."
assert [item["title"].lower() for item in correction["candidates"] if item["type"] == "get_list"] == ["potatoes"]

# Good future ideas live in Holding until they clearly become opportunities or projects.
holding = interpret_fragment("Wouldn't mind learning freediving this summer.")
assert holding["memory_class"] == "reference"
assert any(item["type"] == "holding" for item in holding["candidates"])

print("Harvester routing acceptance tests passed")
