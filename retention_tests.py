from datetime import datetime, timedelta, timezone

from app.retention import normalise_link, retention_status

now = datetime(2026, 8, 19, tzinfo=timezone.utc)
complete = {
    "target_app": "Run & Maintain",
    "target_type": "maintenance item",
    "target_id": "job-1",
    "label": "Fix trailer light",
    "state": "completed",
    "completed_at": (now - timedelta(days=31)).isoformat(),
}
open_link = {**complete, "target_id": "job-2", "state": "open", "completed_at": None}

assert retention_status("permanent", [complete], now)["eligible"] is False
assert retention_status("reference", [complete], now)["eligible"] is False
assert retention_status("transient", [], now)["eligible"] is False
assert retention_status("transient", [open_link], now)["eligible"] is False
assert retention_status("transient", [{**complete, "completed_at": None}], now)["eligible"] is False
assert retention_status("transient", [{**complete, "completed_at": (now - timedelta(days=29)).isoformat()}], now)["eligible"] is False
assert retention_status("transient", [complete], now)["eligible"] is True
assert normalise_link(complete) == complete
assert normalise_link({**complete, "state": "killed"}) is None

print("Fragments retention acceptance tests passed")
