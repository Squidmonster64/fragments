from app.harvester_actions import _idempotency_key

candidate = {"type": "get_list", "title": "Carrots"}
first = _idempotency_key("5:2026-08-20T23:00:00+00:00", candidate)
retry = _idempotency_key("5:2026-08-20T23:00:00+00:00", candidate)
reused_display_code = _idempotency_key("5:2026-08-20T23:00:01+00:00", candidate)

assert first == retry
assert first != reused_display_code
print("immutable Harvester idempotency regression check passed")
