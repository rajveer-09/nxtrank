# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""The Guide's rule book reads its numbers from the code, and none is left out."""

import numbers

from app.services import analytics, rules
from tests.test_api import client_for, env  # noqa: F401  (env is a fixture)

# analytics constants that aren't rules a reader needs (limits and internal names)
NOT_RULES = {"MAX_FILTER_VALUES", "PARTICIPATED", "SORTS", "CONSISTENCY_LABELS"}


def test_every_analytics_threshold_is_in_the_rule_book(env):
    numeric = {name for name, value in vars(analytics).items()
               if name.isupper() and isinstance(value, numbers.Number) and not isinstance(value, bool)}
    missing = numeric - set(rules.ANALYTICS_RULES) - NOT_RULES
    assert not missing, f"add these to rules.ANALYTICS_RULES: {sorted(missing)}"

    book = client_for(env, "viewer").get("/api/rules").json()
    for name in rules.ANALYTICS_RULES:
        assert book["analytics"][name.lower()] == getattr(analytics, name)
    assert book["analytics"]["consistency_labels"][0] == {"from": 80, "label": "Very consistent"}
    assert book["schedule"]["final_time"] == "23:00" and book["schedule"]["scan_delay_minutes"] == 30
    assert book["tags"]["max_tags"] == 4 and book["review"]["draft_days"] == 7


def test_the_rule_book_needs_a_login(env):
    assert client_for(env).get("/api/rules").status_code == 401
