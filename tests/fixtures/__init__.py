"""
Fixture helpers for unit tests.

Usage
-----
from tests.fixtures import load, MOCK_CONFIG, MOCK_GROUP_MEMBER_INFO, MOCK_SW_GROUPS

transaction = load("non_split_transaction")
"""

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"


def load(name: str) -> dict:
    """Load a fixture JSON file by name (omit the .json extension)."""
    path = _DATA_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Shared mock config — mirrors the shape of config.yaml minus real credentials.
# Tag colors here must match the colors used in the fixture JSON files so that
# production routing logic (which compares tag.color to config values) works
# correctly when running against fixture data.
# ---------------------------------------------------------------------------
MOCK_CONFIG = {
    "monarch_user_firstname": "Alex",
    "key_tag_colors": {
        "payee": "#EF12AB",
        "splitwise-group": "#AB89CD",
        "Not In Splitwise": "#EF12CD",
        "In Splitwise": "#9A12CD",
    },
    "easy_descriptions": {
        "TEST MERCHANT": "Test Merchant Friendly Name",
    },
}

# ---------------------------------------------------------------------------
# Group member list matching the payee names/IDs referenced in fixture files.
# ---------------------------------------------------------------------------
MOCK_GROUP_MEMBER_INFO = [
    {"first_name": "Alex",    "memberId": 1001},
    {"first_name": "Jake",    "memberId": 1002},
    {"first_name": "Jasmine", "memberId": 1003},
    {"first_name": "Liam",    "memberId": 1004},
]

# ---------------------------------------------------------------------------
# Splitwise group dict matching the shape returned by Main.get_sw_groups().
# The group name ("Roomies") matches the "Roomies" tag in the fixture files.
# ---------------------------------------------------------------------------
MOCK_SW_GROUPS = {
    "Roomies": {
        "groupId": 9001,
        "members": MOCK_GROUP_MEMBER_INFO,
    }
}
