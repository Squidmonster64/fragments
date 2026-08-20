from app.interpretation import interpret_fragment

CASES = [
    ("shopping", "I just remembered I need to buy some carrots.", {"get_list"}, set(), "transient"),
    ("reminder", "Call Roger next Wednesday on his birthday.", {"reminder"}, set(), "transient"),
    ("maintenance", "The car headlight is out, gotta fix that.", {"run_maintain"}, set(), "transient"),
    ("implied_maintenance", "My office windows are so dirty.", {"run_maintain"}, set(), "transient"),
    ("question", "What's left to do today?", {"ask_ai"}, set(), "reference"),
    ("missing_schedule_question", "Where am I at in my cleaning schedule?", {"ask_ai"}, set(), "reference"),
    ("reflection", "I didn't train again today, I need a break.", {"daybook"}, set(), "reference"),
    ("weekly_review", "We really need to change this plan. Please bring it up in the weekly review.", {"weekly_review"}, set(), "reference"),
    ("decision", "I've decided not to redo the upstairs bathroom until the house becomes a rental because the tax treatment is better.", {"decision"}, set(), "transient"),
    ("permanent_reflection", "I love the warm sun on my face, the fresh cut grass under my feet.", set(), {"run_maintain", "reminder", "get_list", "shitlist"}, "permanent"),
    ("opportunity", "I have a great idea for a book called The Last Handover Note.", {"opportunity"}, {"shitlist"}, "permanent"),
]

failures = []
for name, text, expected_present, expected_absent, expected_memory in CASES:
    result = interpret_fragment(text)
    types = {str(candidate["type"]) for candidate in result["candidates"]}
    memory = str(result["memory_class"])
    present_ok = expected_present <= types
    absent_ok = not (expected_absent & types)
    memory_ok = memory == expected_memory
    status = "PASS" if present_ok and absent_ok and memory_ok else "PARTIAL"
    print(f"{name}|{status}|types={','.join(sorted(types)) or 'none'}|memory={memory}")
    if status != "PASS":
        failures.append(name)

print(f"SUMMARY|passed={len(CASES) - len(failures)}|partial={len(failures)}|partial_cases={','.join(failures) or 'none'}")
