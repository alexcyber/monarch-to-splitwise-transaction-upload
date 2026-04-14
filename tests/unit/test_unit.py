"""
Unit tests for main.py — no real API calls.

All external I/O (Monarch Money, Splitwise, config.yaml) is replaced with
fixtures and mocks.  Every test in this file must be runnable offline with
no credentials configured.

Run:
    python -m unittest tests/unit/test_unit.py
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from main import Main
from tests.fixtures import (
    MOCK_CONFIG,
    MOCK_GROUP_MEMBER_INFO,
    MOCK_SW_GROUPS,
    load,
)


def _make_main() -> Main:
    """Return a Main instance with __init__ bypassed and mocks injected."""
    with patch.object(Main, "__init__", return_value=None):
        instance = Main()
    instance.config = dict(MOCK_CONFIG)
    instance.mm = AsyncMock()
    instance.sw = MagicMock()
    return instance


# ---------------------------------------------------------------------------
# calculate_shares
# ---------------------------------------------------------------------------
class TestCalculateShares(unittest.TestCase):

    def setUp(self):
        self.running = _make_main()

    def test_even_split(self):
        result = self.running.calculate_shares(12.00, 3)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(sum(result), 12.00, places=2)
        self.assertTrue(all(s == 4.00 for s in result))

    def test_uneven_split_391_68_by_5(self):
        result = self.running.calculate_shares(391.68, 5)
        self.assertEqual(len(result), 5)
        self.assertAlmostEqual(sum(result), 391.68, places=2)
        self.assertTrue(all(s in [78.33, 78.34] for s in result))

    def test_uneven_split_313_34_by_4(self):
        result = self.running.calculate_shares(313.34, 4)
        self.assertEqual(len(result), 4)
        self.assertAlmostEqual(sum(result), 313.34, places=2)
        self.assertTrue(all(s in [78.33, 78.34] for s in result))

    def test_two_people_odd_cents(self):
        result = self.running.calculate_shares(1.01, 2)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(sum(result), 1.01, places=2)
        self.assertTrue(all(s in [0.50, 0.51] for s in result))

    def test_single_person_gets_full_amount(self):
        result = self.running.calculate_shares(55.55, 1)
        self.assertEqual(result, [55.55])

    def test_sum_always_equals_input(self):
        for money, n in [(100.00, 3), (7.77, 4), (0.01, 2), (999.99, 7)]:
            with self.subTest(money=money, n=n):
                result = self.running.calculate_shares(money, n)
                self.assertAlmostEqual(sum(result), money, places=2)


# ---------------------------------------------------------------------------
# flatten_list
# ---------------------------------------------------------------------------
class TestFlattenList(unittest.TestCase):

    def setUp(self):
        self.running = _make_main()

    def test_already_flat(self):
        self.assertEqual(self.running.flatten_list([1, 2, 3]), [1, 2, 3])

    def test_one_level_nested(self):
        self.assertEqual(self.running.flatten_list([[1, 2], [3]]), [1, 2, 3])

    def test_deeply_nested(self):
        self.assertEqual(self.running.flatten_list([[[1], 2], [3]]), [1, 2, 3])

    def test_empty(self):
        self.assertEqual(self.running.flatten_list([]), [])

    def test_mixed_depth(self):
        self.assertEqual(
            self.running.flatten_list([1, [2, [3, 4]]]),
            [1, 2, 3, 4],
        )

    def test_preserves_order(self):
        nested = [[3, 1], [4, 1, 5], [9, 2, 6]]
        self.assertEqual(self.running.flatten_list(nested), [3, 1, 4, 1, 5, 9, 2, 6])


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------
class TestLoadConfig(unittest.TestCase):

    @patch.dict(
        os.environ,
        {
            "sw_consumer_key": "test_key",
            "sw_consumer_secret": "test_secret",
            "sw_api_key": "test_api",
            "isLambda": "True",
        },
        clear=True,
    )
    def test_lambda_reads_from_env(self):
        with patch.object(Main, "__init__", return_value=None):
            instance = Main()
        result = instance.load_config()
        self.assertEqual(
            result,
            {
                "sw_consumer_key": "test_key",
                "sw_consumer_secret": "test_secret",
                "sw_api_key": "test_api",
            },
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_non_lambda_reads_yaml(self):
        """When isLambda is absent, load_config opens config.yaml."""
        mock_yaml = {"some_key": "some_value"}
        with patch.object(Main, "__init__", return_value=None):
            instance = Main()
        with patch("builtins.open", unittest.mock.mock_open(read_data="")), \
             patch("yaml.safe_load", return_value=mock_yaml):
            result = instance.load_config()
        self.assertEqual(result, mock_yaml)


# ---------------------------------------------------------------------------
# compute_shares  (async)
# ---------------------------------------------------------------------------
class TestComputeShares(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.running = _make_main()
        self.non_split = load("non_split_transaction")
        self.child1 = load("split_child_1")

    async def test_single_payee_owed_share_equals_amount(self):
        """One payee → owed_share equals the full transaction amount."""
        transaction = {
            "getTransaction": {
                "amount": -50.00,
                "isSplitTransaction": False,
                "originalTransaction": None,
                "tags": [
                    {"name": "Alex", "color": "#EF12AB"},
                ],
            }
        }
        result = await self.running.compute_shares(transaction, MOCK_GROUP_MEMBER_INFO)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["owed-share"], 50.00, places=2)

    async def test_multiple_payees_sum_equals_amount(self):
        """Three payees → sum of owed-shares equals transaction amount."""
        result = await self.running.compute_shares(self.non_split, MOCK_GROUP_MEMBER_INFO)
        total = sum(e["owed-share"] for e in result)
        self.assertAlmostEqual(total, 120.00, places=2)

    async def test_multiple_payees_count(self):
        result = await self.running.compute_shares(self.non_split, MOCK_GROUP_MEMBER_INFO)
        self.assertEqual(len(result), 3)  # Alex, Jake, Jasmine

    async def test_paid_share_always_zero(self):
        """compute_shares no longer assigns paid-share — build_user_share_entries does,
        centrally, so root's paid-share is not double-counted across split children."""
        result = await self.running.compute_shares(self.non_split, MOCK_GROUP_MEMBER_INFO)
        for entry in result:
            self.assertEqual(entry["paid-share"], 0.00)

    async def test_unknown_payee_name_sets_user_id_none(self):
        """A payee tag whose name does not appear in group_member_info produces userId=None."""
        transaction = {
            "getTransaction": {
                "amount": -30.00,
                "isSplitTransaction": False,
                "originalTransaction": None,
                "tags": [
                    {"name": "Ghost", "color": "#EF12AB"},
                ],
            }
        }
        result = await self.running.compute_shares(transaction, MOCK_GROUP_MEMBER_INFO)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["userId"])

    async def test_user_ids_match_group_member_info(self):
        """Returned userId values must correspond to the correct member."""
        result = await self.running.compute_shares(self.non_split, MOCK_GROUP_MEMBER_INFO)
        id_map = {m["first_name"]: m["memberId"] for m in MOCK_GROUP_MEMBER_INFO}
        for entry in result:
            self.assertEqual(entry["userId"], id_map[entry["name"]])

    async def test_split_child_owed_share_equals_child_amount(self):
        """For a split child with a single payee, owed-share equals the child amount."""
        result = await self.running.compute_shares(self.child1, MOCK_GROUP_MEMBER_INFO)
        total = sum(e["owed-share"] for e in result)
        self.assertAlmostEqual(total, 60.00, places=2)

    async def test_fallback_to_group_members_when_no_payee_tags(self):
        """When a transaction has a group tag but no payee tags, compute_shares
        splits evenly across every group member (instead of crashing with div-by-zero)."""
        transaction = {
            "getTransaction": {
                "amount": -40.00,
                "isSplitTransaction": False,
                "originalTransaction": None,
                "tags": [
                    {"name": "Roomies", "color": "#AB89CD"},
                ],
            }
        }
        result = await self.running.compute_shares(transaction, MOCK_GROUP_MEMBER_INFO)
        self.assertEqual(len(result), len(MOCK_GROUP_MEMBER_INFO))
        total = sum(e["owed-share"] for e in result)
        self.assertAlmostEqual(total, 40.00, places=2)
        names = {e["name"] for e in result}
        self.assertEqual(names, {m["first_name"] for m in MOCK_GROUP_MEMBER_INFO})

    async def test_refund_amount_uses_abs_value(self):
        """A positive-amount (refund) transaction produces positive owed-shares,
        which is required before the refund transform can run."""
        transaction = {
            "getTransaction": {
                "amount": 20.00,  # positive = refund in Monarch
                "isSplitTransaction": False,
                "originalTransaction": None,
                "tags": [
                    {"name": "Alex", "color": "#EF12AB"},
                ],
            }
        }
        result = await self.running.compute_shares(transaction, MOCK_GROUP_MEMBER_INFO)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["owed-share"], 20.00, places=2)


# ---------------------------------------------------------------------------
# get_groupId_transaction  (async)
# ---------------------------------------------------------------------------
class TestGetGroupIdTransaction(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.running = _make_main()
        self.non_split = load("non_split_transaction")
        self.split_parent = load("split_parent_transaction")
        self.child1 = load("split_child_1")

    async def test_non_split_returns_same_object(self):
        result = await self.running.get_groupId_transaction(self.non_split)
        self.assertIs(result, self.non_split)

    async def test_non_split_does_not_call_mm(self):
        await self.running.get_groupId_transaction(self.non_split)
        self.running.mm.get_transaction_details.assert_not_called()

    async def test_split_calls_mm_with_first_child_id(self):
        self.running.mm.get_transaction_details = AsyncMock(return_value=self.child1)
        await self.running.get_groupId_transaction(self.split_parent)
        first_child_id = self.split_parent["getTransaction"]["splitTransactions"][0]["id"]
        self.running.mm.get_transaction_details.assert_called_once_with(first_child_id)

    async def test_split_returns_child_details(self):
        self.running.mm.get_transaction_details = AsyncMock(return_value=self.child1)
        result = await self.running.get_groupId_transaction(self.split_parent)
        self.assertEqual(result, self.child1)


# ---------------------------------------------------------------------------
# get_group_metadata  (async)
# ---------------------------------------------------------------------------
class TestGetGroupMetadata(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.running = _make_main()
        self.non_split = load("non_split_transaction")
        self.split_parent = load("split_parent_transaction")
        self.child1 = load("split_child_1")

    async def test_no_tags_raises_value_error(self):
        """A transaction with an empty tags list must raise ValueError."""
        empty_tags_transaction = {
            "getTransaction": {
                "id": "999",
                "hasSplitTransactions": False,
                "tags": [],
            }
        }
        with self.assertRaises(ValueError):
            await self.running.get_group_metadata(MOCK_SW_GROUPS, empty_tags_transaction)

    async def test_matching_group_returns_correct_values(self):
        group_id, group_name, members, txn = await self.running.get_group_metadata(
            MOCK_SW_GROUPS, self.non_split
        )
        self.assertEqual(group_id, 9001)
        self.assertEqual(group_name, "Roomies")
        self.assertEqual(members, MOCK_GROUP_MEMBER_INFO)
        self.assertIs(txn, self.non_split)

    async def test_no_matching_group_returns_none_values(self):
        """A tag with group color but no matching SW group name returns all None."""
        unknown_group_transaction = {
            "getTransaction": {
                "id": "888",
                "hasSplitTransactions": False,
                "tags": [
                    {"name": "Unknown Group", "color": "#AB89CD"},
                ],
            }
        }
        group_id, group_name, members, txn = await self.running.get_group_metadata(
            MOCK_SW_GROUPS, unknown_group_transaction
        )
        self.assertIsNone(group_id)
        self.assertIsNone(group_name)
        self.assertIsNone(members)

    async def test_split_parent_uses_first_child_for_group_tag(self):
        """For split transactions, group metadata is read from first child, not parent."""
        self.running.mm.get_transaction_details = AsyncMock(return_value=self.child1)
        group_id, group_name, members, txn = await self.running.get_group_metadata(
            MOCK_SW_GROUPS, self.split_parent
        )
        self.assertEqual(group_id, 9001)
        self.assertEqual(group_name, "Roomies")
        # Returned transaction should be the child, not the parent
        self.assertEqual(txn["getTransaction"]["id"], self.child1["getTransaction"]["id"])


# ---------------------------------------------------------------------------
# build_user_share_entries  (async)
# ---------------------------------------------------------------------------
class TestBuildUserShareEntries(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.running = _make_main()
        self.non_split = load("non_split_transaction")
        self.no_root = load("non_split_no_root_transaction")
        self.split_parent = load("split_parent_transaction")
        self.child1 = load("split_child_1")
        self.child2 = load("split_child_2")

    async def test_non_split_returns_list_of_dicts(self):
        result = await self.running.build_user_share_entries(
            self.non_split, MOCK_GROUP_MEMBER_INFO
        )
        self.assertIsInstance(result, list)
        self.assertTrue(all(isinstance(e, dict) for e in result))

    async def test_non_split_result_has_expected_keys(self):
        result = await self.running.build_user_share_entries(
            self.non_split, MOCK_GROUP_MEMBER_INFO
        )
        for entry in result:
            self.assertIn("name", entry)
            self.assertIn("userId", entry)
            self.assertIn("paid-share", entry)
            self.assertIn("owed-share", entry)

    async def test_non_split_total_owed_share_equals_amount(self):
        result = await self.running.build_user_share_entries(
            self.non_split, MOCK_GROUP_MEMBER_INFO
        )
        total = sum(e["owed-share"] for e in result)
        self.assertAlmostEqual(total, 120.00, places=2)

    async def test_non_split_root_user_present_in_result(self):
        result = await self.running.build_user_share_entries(
            self.non_split, MOCK_GROUP_MEMBER_INFO
        )
        names = [e["name"] for e in result]
        self.assertIn("Alex", names)

    async def test_split_parent_iterates_children(self):
        """Each split child is fetched via mm and contributes entries."""
        child_map = {
            self.child1["getTransaction"]["id"]: self.child1,
            self.child2["getTransaction"]["id"]: self.child2,
        }
        self.running.mm.get_transaction_details = AsyncMock(
            side_effect=lambda tid: child_map[tid]
        )
        result = await self.running.build_user_share_entries(
            self.split_parent, MOCK_GROUP_MEMBER_INFO
        )
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    async def test_split_parent_total_owed_share(self):
        """Sum of owed-shares across both children should equal combined child amounts."""
        child_map = {
            self.child1["getTransaction"]["id"]: self.child1,
            self.child2["getTransaction"]["id"]: self.child2,
        }
        self.running.mm.get_transaction_details = AsyncMock(
            side_effect=lambda tid: child_map[tid]
        )
        result = await self.running.build_user_share_entries(
            self.split_parent, MOCK_GROUP_MEMBER_INFO
        )
        total = sum(e["owed-share"] for e in result)
        # child1 = $60, child2 = $40 → total $100
        self.assertAlmostEqual(total, 100.00, places=2)

    async def test_split_parent_total_paid_share_equals_cost(self):
        """sum(paid-share) == parent cost when root user is tagged in a split child.
        Root's paid-share is set from originalTransaction.amount, not the child amount."""
        child_map = {
            self.child1["getTransaction"]["id"]: self.child1,
            self.child2["getTransaction"]["id"]: self.child2,
        }
        self.running.mm.get_transaction_details = AsyncMock(
            side_effect=lambda tid: child_map[tid]
        )
        result = await self.running.build_user_share_entries(
            self.split_parent, MOCK_GROUP_MEMBER_INFO
        )
        cost = self.split_parent["getTransaction"]["amount"] * -1
        total_paid = sum(e["paid-share"] for e in result)
        self.assertAlmostEqual(total_paid, cost, places=2)

    async def test_non_split_total_paid_share_equals_cost(self):
        """sum(paid-share) must equal the transaction cost — the exact invariant
        Splitwise enforces. Regression guard for the root-user paid-share bug."""
        result = await self.running.build_user_share_entries(
            self.non_split, MOCK_GROUP_MEMBER_INFO
        )
        cost = self.non_split["getTransaction"]["amount"] * -1
        total_paid = sum(e["paid-share"] for e in result)
        self.assertAlmostEqual(total_paid, cost, places=2)

    async def test_no_root_total_paid_share_equals_cost(self):
        """When root user is absent from tags and gets auto-injected, the injected
        paid-share must bring sum(paid-share) up to the full transaction cost."""
        result = await self.running.build_user_share_entries(
            self.no_root, MOCK_GROUP_MEMBER_INFO
        )
        cost = self.no_root["getTransaction"]["amount"] * -1
        total_paid = sum(e["paid-share"] for e in result)
        self.assertAlmostEqual(total_paid, cost, places=2)

    async def test_split_no_root_adds_root_user_with_paid_share(self):
        """When neither split child tags the root user, build_user_share_entries
        must still inject the root user with owed-share=0 and paid-share=parent amount."""
        split_no_root_parent = load("split_no_root_parent")
        child1 = load("split_no_root_child_1")
        child2 = load("split_no_root_child_2")
        child_map = {
            child1["getTransaction"]["id"]: child1,
            child2["getTransaction"]["id"]: child2,
        }
        self.running.mm.get_transaction_details = AsyncMock(
            side_effect=lambda tid: child_map[tid]
        )
        result = await self.running.build_user_share_entries(
            split_no_root_parent, MOCK_GROUP_MEMBER_INFO
        )
        names = [e["name"] for e in result]
        self.assertIn("Alex", names)
        alex = next(e for e in result if e["name"] == "Alex")
        self.assertEqual(alex["owed-share"], 0)
        self.assertAlmostEqual(alex["paid-share"], 80.00, places=2)

    async def test_split_no_root_total_paid_share_equals_cost(self):
        """sum(paid-share) == parent cost even when root user is auto-injected
        into a split transaction."""
        split_no_root_parent = load("split_no_root_parent")
        child1 = load("split_no_root_child_1")
        child2 = load("split_no_root_child_2")
        child_map = {
            child1["getTransaction"]["id"]: child1,
            child2["getTransaction"]["id"]: child2,
        }
        self.running.mm.get_transaction_details = AsyncMock(
            side_effect=lambda tid: child_map[tid]
        )
        result = await self.running.build_user_share_entries(
            split_no_root_parent, MOCK_GROUP_MEMBER_INFO
        )
        cost = split_no_root_parent["getTransaction"]["amount"] * -1
        total_paid = sum(e["paid-share"] for e in result)
        self.assertAlmostEqual(total_paid, cost, places=2)

    async def test_root_user_absent_from_tags_is_added_with_zero_owed(self):
        """When the root user is not tagged as a payee, build_user_share_entries must
        add them automatically with owed-share=0 and paid-share=full amount so that
        Splitwise's paid-share validation passes."""
        result = await self.running.build_user_share_entries(
            self.no_root, MOCK_GROUP_MEMBER_INFO
        )
        names = [e["name"] for e in result]
        self.assertIn("Alex", names)
        alex = next(e for e in result if e["name"] == "Alex")
        self.assertEqual(alex["owed-share"], 0)
        self.assertAlmostEqual(alex["paid-share"], 90.00, places=2)


# ---------------------------------------------------------------------------
# merge_user_shares
# ---------------------------------------------------------------------------
class TestMergeUserShares(unittest.TestCase):

    def setUp(self):
        self.running = _make_main()

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.running.merge_user_shares([]), [])

    def test_all_unique_ids_unchanged(self):
        entries = [
            {"name": "Alex", "userId": 1001, "paid-share": 10.0, "owed-share": 5.0},
            {"name": "Jake", "userId": 1002, "paid-share": 0.0,  "owed-share": 5.0},
        ]
        result = self.running.merge_user_shares(entries)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(sum(e["owed-share"] for e in result), 10.0, places=2)

    def test_duplicate_ids_merged_into_one(self):
        entries = [
            {"name": "Alex", "userId": 1001, "paid-share": 0.0, "owed-share": 0.44},
            {"name": "Alex", "userId": 1001, "paid-share": 0.0, "owed-share": 0.24},
        ]
        result = self.running.merge_user_shares(entries)
        self.assertEqual(len(result), 1)

    def test_duplicate_owed_shares_summed(self):
        entries = [
            {"name": "Alex", "userId": 1001, "paid-share": 0.0, "owed-share": 0.44},
            {"name": "Alex", "userId": 1001, "paid-share": 0.0, "owed-share": 0.24},
        ]
        result = self.running.merge_user_shares(entries)
        self.assertAlmostEqual(result[0]["owed-share"], 0.68, places=2)

    def test_duplicate_paid_shares_summed(self):
        entries = [
            {"name": "Alex", "userId": 1001, "paid-share": 5.0, "owed-share": 3.0},
            {"name": "Alex", "userId": 1001, "paid-share": 3.0, "owed-share": 2.0},
        ]
        result = self.running.merge_user_shares(entries)
        self.assertAlmostEqual(result[0]["paid-share"], 8.0, places=2)
        self.assertAlmostEqual(result[0]["owed-share"], 5.0, places=2)

    def test_partial_duplicates_only_duplicates_merged(self):
        entries = [
            {"name": "Alex", "userId": 1001, "paid-share": 0.0, "owed-share": 0.44},
            {"name": "Alex", "userId": 1001, "paid-share": 0.0, "owed-share": 0.24},
            {"name": "Jake", "userId": 1002, "paid-share": 0.68, "owed-share": 0.0},
        ]
        result = self.running.merge_user_shares(entries)
        self.assertEqual(len(result), 2)
        alex = next(e for e in result if e["userId"] == 1001)
        jake = next(e for e in result if e["userId"] == 1002)
        self.assertAlmostEqual(alex["owed-share"], 0.68, places=2)
        self.assertAlmostEqual(jake["paid-share"], 0.68, places=2)


# ---------------------------------------------------------------------------
# Regression: split transaction with same payee in both children (Bug 1)
# ---------------------------------------------------------------------------
class TestDuplicatePayeeRegression(unittest.IsolatedAsyncioTestCase):
    """
    Regression guard for the 'A person was included on this expense multiple
    times' Splitwise error.  Triggered when a split transaction has the same
    payee tagged in every child — each compute_shares call returned a separate
    entry for that payee, causing Splitwise to reject the expense.
    """

    def setUp(self):
        self.running = _make_main()
        self.parent = load("split_same_payee_parent")
        self.child1 = load("split_same_payee_child_1")
        self.child2 = load("split_same_payee_child_2")
        child_map = {
            self.child1["getTransaction"]["id"]: self.child1,
            self.child2["getTransaction"]["id"]: self.child2,
        }
        self.running.mm.get_transaction_details = AsyncMock(
            side_effect=lambda tid: child_map[tid]
        )

    async def test_same_payee_in_both_children_appears_once(self):
        """Alex is tagged in both children — must appear only once in the result."""
        result = await self.running.build_user_share_entries(
            self.parent, MOCK_GROUP_MEMBER_INFO
        )
        alex_entries = [e for e in result if e["name"] == "Alex"]
        self.assertEqual(len(alex_entries), 1, "Alex should appear exactly once")

    async def test_same_payee_owed_share_is_sum_of_children(self):
        """Alex's owed-share must be the sum of both child amounts (0.44 + 0.24 = 0.68)."""
        result = await self.running.build_user_share_entries(
            self.parent, MOCK_GROUP_MEMBER_INFO
        )
        alex = next(e for e in result if e["name"] == "Alex")
        self.assertAlmostEqual(alex["owed-share"], 0.68, places=2)

    async def test_no_duplicate_user_ids_in_result(self):
        """No userId should appear more than once — the invariant Splitwise enforces."""
        result = await self.running.build_user_share_entries(
            self.parent, MOCK_GROUP_MEMBER_INFO
        )
        user_ids = [e["userId"] for e in result]
        self.assertEqual(len(user_ids), len(set(user_ids)), "Duplicate userId found in result")

    async def test_root_paid_share_not_double_counted(self):
        """When root user is tagged in multiple split children, paid-share must equal
        parent amount once — not N × parent. Regression for a bug that was hidden by
        the duplicate-user error but would have produced paid=1.36 for a 0.68 parent."""
        result = await self.running.build_user_share_entries(
            self.parent, MOCK_GROUP_MEMBER_INFO
        )
        alex = next(e for e in result if e["name"] == "Alex")
        parent_amount = abs(self.parent["getTransaction"]["amount"])
        self.assertAlmostEqual(alex["paid-share"], parent_amount, places=2)

    async def test_split_same_payee_total_paid_equals_cost(self):
        """sum(paid-share) must equal parent cost exactly — Splitwise's invariant."""
        result = await self.running.build_user_share_entries(
            self.parent, MOCK_GROUP_MEMBER_INFO
        )
        total_paid = sum(e["paid-share"] for e in result)
        parent_amount = abs(self.parent["getTransaction"]["amount"])
        self.assertAlmostEqual(total_paid, parent_amount, places=2)


# ---------------------------------------------------------------------------
# to_refund_shares
# ---------------------------------------------------------------------------
class TestToRefundShares(unittest.TestCase):
    """Reverse-roles refund transformation.  See to_refund_shares docstring for model."""

    def setUp(self):
        self.running = _make_main()

    def test_two_person_uneven_split(self):
        """$20 refund, 70/30 split (root paid) → cost $6, root owes $6, friend paid $6."""
        normal_shares = [
            {"name": "Alex", "userId": 1001, "paid-share": 20.00, "owed-share": 14.00},
            {"name": "Jake", "userId": 1002, "paid-share": 0.00,  "owed-share": 6.00},
        ]
        new_shares, new_cost = self.running.to_refund_shares(normal_shares)
        self.assertAlmostEqual(new_cost, 6.00, places=2)
        alex = next(e for e in new_shares if e["name"] == "Alex")
        jake = next(e for e in new_shares if e["name"] == "Jake")
        self.assertEqual(alex["paid-share"], 0)
        self.assertAlmostEqual(alex["owed-share"], 6.00, places=2)
        self.assertAlmostEqual(jake["paid-share"], 6.00, places=2)
        self.assertEqual(jake["owed-share"], 0)

    def test_three_person_even_split(self):
        """$15 refund, 3-way even split → each non-root gets back $5, root owes $10."""
        normal_shares = [
            {"name": "Alex",    "userId": 1001, "paid-share": 15.00, "owed-share": 5.00},
            {"name": "Jake",    "userId": 1002, "paid-share": 0.00,  "owed-share": 5.00},
            {"name": "Jasmine", "userId": 1003, "paid-share": 0.00,  "owed-share": 5.00},
        ]
        new_shares, new_cost = self.running.to_refund_shares(normal_shares)
        self.assertAlmostEqual(new_cost, 10.00, places=2)
        alex = next(e for e in new_shares if e["name"] == "Alex")
        self.assertAlmostEqual(alex["owed-share"], 10.00, places=2)
        for other in ["Jake", "Jasmine"]:
            entry = next(e for e in new_shares if e["name"] == other)
            self.assertAlmostEqual(entry["paid-share"], 5.00, places=2)
            self.assertEqual(entry["owed-share"], 0)

    def test_sum_paid_equals_sum_owed_equals_cost(self):
        """Splitwise invariant: sum(paid) == sum(owed) == cost."""
        normal_shares = [
            {"name": "Alex", "userId": 1001, "paid-share": 20.00, "owed-share": 14.00},
            {"name": "Jake", "userId": 1002, "paid-share": 0.00,  "owed-share": 6.00},
        ]
        new_shares, new_cost = self.running.to_refund_shares(normal_shares)
        self.assertAlmostEqual(sum(e["paid-share"] for e in new_shares), new_cost, places=2)
        self.assertAlmostEqual(sum(e["owed-share"] for e in new_shares), new_cost, places=2)

    def test_root_only_refund_has_zero_cost(self):
        """If root was the only payee, no group balance changes — cost = 0 → will be skipped."""
        normal_shares = [
            {"name": "Alex", "userId": 1001, "paid-share": 30.00, "owed-share": 30.00},
        ]
        new_shares, new_cost = self.running.to_refund_shares(normal_shares)
        self.assertEqual(new_cost, 0)

    def test_balance_shift_matches_expected_math(self):
        """$20 refund, 70/30 original. Friend's starting debt $30 → should become $24 (drop $6)."""
        normal_shares = [
            {"name": "Alex", "userId": 1001, "paid-share": 20.00, "owed-share": 14.00},
            {"name": "Jake", "userId": 1002, "paid-share": 0.00,  "owed-share": 6.00},
        ]
        new_shares, _ = self.running.to_refund_shares(normal_shares)
        jake = next(e for e in new_shares if e["name"] == "Jake")
        # Jake net = paid - owed = +6 → debt decreases by $6 ✓
        jake_net_change = jake["paid-share"] - jake["owed-share"]
        self.assertAlmostEqual(jake_net_change, 6.00, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
