"""
Integration tests for main.py — makes real API calls to Monarch Money.

Design principle: test values are owned by this file, not by config.yaml.
Config.yaml supplies only Monarch wiring (IDs and credentials); all amounts,
member counts, expected values, and root identity are fixed constants here
so that assertions don't drift when the user's config changes.

Requirements in config.yaml:
  - test_mon_account_id       : Monarch account ID for creating test transactions
  - test_mon_category_id      : Monarch category ID used to tag test transactions
  - test_sw_group_member_info : list of {Name, id, is_root} — the test picks a
                                fixed subset (NON_ROOT_COUNT non-root entries)
  - test_root_user            : list with single {id, Name} entry for the root user
  - test_group_id             : dict {"test": {"id": <tag_id>}}
  - test_action_tag           : tag ID for "Not In Splitwise"

These tests create and delete real Monarch transactions.  Do not run in
production; use a dedicated test account.

Run:
    python -m unittest tests/integration/test_integration.py
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from main import Main


# -----------------------------------------------------------------------------
# Test-owned fixtures.  Amounts are intentionally non-round so that even splits
# leave remainder cents and any rounding/fairness bug surfaces.  Member count
# is fixed so expected values are deterministic regardless of config.yaml size.
# -----------------------------------------------------------------------------
NON_ROOT_COUNT = 3

NON_SPLIT_AMOUNT = 1337.13
SPLIT_PARENT_AMOUNT = -391.68
SPLIT_CHILD_REIMBURSEE_AMOUNT = -78.34      # root-only payee
SPLIT_CHILD_REPAYER_AMOUNT = -313.34        # non-root payees; 313.34/3 = 104.44666...
REFUND_AMOUNT = 17.89                       # positive → refund flow; 17.89/3 = 5.9633...
SAME_PAYEE_PARENT_AMOUNT = -77.53
SAME_PAYEE_CHILD_1_AMOUNT = -43.21
SAME_PAYEE_CHILD_2_AMOUNT = -34.32          # sum = -77.53
GROUP_ONLY_AMOUNT = -41.73                  # 41.73/4 = 10.4325, forces remainder


class TestIntegration(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        cls.running = Main()
        cls.running_config = cls.running.load_config()
        cls.created_transactions = {}
        cls.transactions_left = []

    @classmethod
    def tearDownClass(cls):
        undeleteable_transactions = []
        for transaction_id in cls.transactions_left:
            is_deleted = asyncio.run(cls.running.mm.delete_transaction(transaction_id))
            if not is_deleted:
                undeleteable_transactions.append(transaction_id)
        if undeleteable_transactions:
            print("There were some test transactions that were not deleted.")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(cls._async_tear_down())
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    @classmethod
    async def _async_tear_down(cls):
        """Delete all test-category transactions — runs once after all tests complete."""
        test_category_id = cls.running_config["test_mon_category_id"]
        transactions = await cls.running.mm.get_transactions(
            category_ids=[test_category_id]
        )
        for transaction in transactions["allTransactions"]["results"]:
            await cls.running.mm.delete_transaction(transaction["id"])

    async def asyncSetUp(self):
        # Fixed test group: 1 root + NON_ROOT_COUNT non-root members taken from config.
        # Expected values in tests depend on NON_ROOT_COUNT, not on config length.
        root_entry = self.running_config["test_root_user"][0]
        self.test_root = {"Name": root_entry["Name"], "id": root_entry["id"]}
        non_root_all = [
            {"Name": m["Name"], "id": m["id"]}
            for m in self.running_config["test_sw_group_member_info"]
            if not m.get("is_root", False)
        ]
        assert len(non_root_all) >= NON_ROOT_COUNT, (
            f"test_sw_group_member_info must contain at least {NON_ROOT_COUNT} "
            f"non-root entries; found {len(non_root_all)}"
        )
        self.test_non_root = non_root_all[:NON_ROOT_COUNT]
        # Decouple production root identity from test root so assertions are stable.
        self.running.config["monarch_user_firstname"] = self.test_root["Name"]

        await self.create_non_split_transaction()
        await self.create_split_transaction()
        await self.create_refund_non_split_transaction()
        await self.create_split_same_payee_transaction()
        await self.create_group_only_transaction()
        self.addAsyncCleanup(self.cleanup_created_transactions)

    async def cleanup_created_transactions(self):
        for transaction_id in self.created_transactions.values():
            is_deleted = await self.running.mm.delete_transaction(transaction_id)
            if not is_deleted:
                self.transactions_left.append(transaction_id)

    # ------------------------------------------------------------------
    # Helpers (test-owned)
    # ------------------------------------------------------------------

    def _group_member_info(self):
        """The Splitwise group_member_info argument for the fixed test subset."""
        members = [{"first_name": self.test_root["Name"], "memberId": self.test_root["id"]}]
        for m in self.test_non_root:
            members.append({"first_name": m["Name"], "memberId": m["id"]})
        return members

    def _non_root_ids(self):
        return [m["id"] for m in self.test_non_root]

    def _all_member_ids(self):
        return [self.test_root["id"]] + self._non_root_ids()

    # ------------------------------------------------------------------
    # Transaction factory helpers
    # ------------------------------------------------------------------

    async def create_non_split_transaction(self):
        test_transac = await self.running.mm.create_transaction(
            date="2019-08-08",
            account_id=self.running_config["test_mon_account_id"],
            amount=NON_SPLIT_AMOUNT,
            merchant_name="TEST_TRANSACTION",
            category_id=self.running_config["test_mon_category_id"],
            notes="TEST TRANSACTION - Not Split",
        )
        await self.set_test_tag_scheme(
            test_transac["createTransaction"]["transaction"]["id"],
            "not-split",
            self._all_member_ids(),
        )
        self.created_transactions["not-split"] = test_transac["createTransaction"]["transaction"]["id"]

    async def create_split_transaction(self):
        parent_total = SPLIT_PARENT_AMOUNT
        split_amounts = [SPLIT_CHILD_REIMBURSEE_AMOUNT, SPLIT_CHILD_REPAYER_AMOUNT]
        tolerance = 1e-2
        assert abs(sum(split_amounts) - parent_total) < tolerance

        date = "2019-08-09"
        account_id = self.running_config["test_mon_account_id"]
        merchant_name = "TEST_TRANSACTION"
        category_id = self.running_config["test_mon_category_id"]

        parent_transaction = await self.running.mm.create_transaction(
            date=date,
            account_id=account_id,
            amount=parent_total,
            merchant_name=merchant_name,
            category_id=category_id,
            notes="Split transaction - Parent",
        )
        parent_transaction_id = parent_transaction["createTransaction"]["transaction"]["id"]
        self.created_transactions["split-parent"] = parent_transaction_id

        split_data = [
            {"merchantName": merchant_name, "amount": split_amounts[0], "categoryId": str(category_id)},
            {"merchantName": merchant_name, "amount": split_amounts[1], "categoryId": str(category_id)},
        ]
        parent_transaction = await self.running.mm.update_transaction_splits(
            transaction_id=parent_transaction_id,
            split_data=split_data,
        )

        child_reimbursee_id = parent_transaction["updateTransactionSplit"]["transaction"]["splitTransactions"][0]["id"]
        child_repayer_id = parent_transaction["updateTransactionSplit"]["transaction"]["splitTransactions"][1]["id"]

        await self.set_test_tag_scheme(
            child_reimbursee_id,
            "split-child-reimbursee",
            self._all_member_ids(),
        )
        await self.set_test_tag_scheme(
            child_repayer_id,
            "split-child-repayer",
            self._non_root_ids(),
        )
        self.created_transactions["split-child-reimbursee"] = child_reimbursee_id
        self.created_transactions["split-child-repayer"] = child_repayer_id

    async def create_refund_non_split_transaction(self):
        '''Positive-amount transaction = refund/income in Monarch.  Same tag scheme
        as a regular non-split expense; the refund transform is applied downstream.'''
        test_transac = await self.running.mm.create_transaction(
            date="2019-08-10",
            account_id=self.running_config["test_mon_account_id"],
            amount=REFUND_AMOUNT,
            merchant_name="TEST_TRANSACTION_REFUND",
            category_id=self.running_config["test_mon_category_id"],
            notes="TEST TRANSACTION - Refund, Not Split",
        )
        await self.set_test_tag_scheme(
            test_transac["createTransaction"]["transaction"]["id"],
            "not-split",
            self._all_member_ids(),
        )
        self.created_transactions["refund-non-split"] = test_transac["createTransaction"]["transaction"]["id"]

    async def create_split_same_payee_transaction(self):
        '''Split transaction where both children tag the same payee (root user only).
        Regression fixture for Splitwise's "person included multiple times" error.'''
        parent_total = SAME_PAYEE_PARENT_AMOUNT
        split_amounts = [SAME_PAYEE_CHILD_1_AMOUNT, SAME_PAYEE_CHILD_2_AMOUNT]
        tolerance = 1e-2
        assert abs(sum(split_amounts) - parent_total) < tolerance

        date = "2019-08-11"
        account_id = self.running_config["test_mon_account_id"]
        merchant_name = "TEST_TRANSACTION_SAME_PAYEE"
        category_id = self.running_config["test_mon_category_id"]

        parent_transaction = await self.running.mm.create_transaction(
            date=date,
            account_id=account_id,
            amount=parent_total,
            merchant_name=merchant_name,
            category_id=category_id,
            notes="Split same-payee - Parent",
        )
        parent_transaction_id = parent_transaction["createTransaction"]["transaction"]["id"]
        self.created_transactions["same-payee-split-parent"] = parent_transaction_id

        split_data = [
            {"merchantName": merchant_name, "amount": split_amounts[0], "categoryId": str(category_id)},
            {"merchantName": merchant_name, "amount": split_amounts[1], "categoryId": str(category_id)},
        ]
        parent_transaction = await self.running.mm.update_transaction_splits(
            transaction_id=parent_transaction_id,
            split_data=split_data,
        )

        child_1_id = parent_transaction["updateTransactionSplit"]["transaction"]["splitTransactions"][0]["id"]
        child_2_id = parent_transaction["updateTransactionSplit"]["transaction"]["splitTransactions"][1]["id"]

        # Both children get root as their sole payee → merge_user_shares must consolidate.
        await self.set_test_tag_scheme(child_1_id, "split-child-reimbursee", [])
        await self.set_test_tag_scheme(child_2_id, "split-child-reimbursee", [])
        self.created_transactions["same-payee-split-child-1"] = child_1_id
        self.created_transactions["same-payee-split-child-2"] = child_2_id

    async def create_group_only_transaction(self):
        '''Group tagged but no payee tags — exercises the even-split fallback in compute_shares.'''
        test_transac = await self.running.mm.create_transaction(
            date="2019-08-12",
            account_id=self.running_config["test_mon_account_id"],
            amount=GROUP_ONLY_AMOUNT,
            merchant_name="TEST_TRANSACTION_GROUP_ONLY",
            category_id=self.running_config["test_mon_category_id"],
            notes="TEST TRANSACTION - Group only, no payees",
        )
        await self.set_test_tag_scheme(
            test_transac["createTransaction"]["transaction"]["id"],
            "group-only",
            [],
        )
        self.created_transactions["group-only"] = test_transac["createTransaction"]["transaction"]["id"]

    async def set_test_tag_scheme(self, transaction_id, scheme, group_member_ids):
        if scheme == "not-split":
            tag_dict = {
                "group_tag_id": self.running_config["test_group_id"]["test"]["id"],
                "payee": self.test_root["id"],
                "group_members": group_member_ids,
                "action_tag": self.running_config["test_action_tag"],
            }
        elif scheme == "split - parent":
            raise NotImplementedError("Split parent tag scheme not implemented")
        elif scheme == "split-child-reimbursee":
            tag_dict = {
                "group_tag_id": self.running_config["test_group_id"]["test"]["id"],
                "payee": self.test_root["id"],
                "action_tag": self.running_config["test_action_tag"],
            }
        elif scheme == "split-child-repayer":
            tag_dict = {
                "group_tag_id": self.running_config["test_group_id"]["test"]["id"],
                "group_members": group_member_ids,
                "action_tag": self.running_config["test_action_tag"],
            }
        elif scheme == "group-only":
            # Group colored tag + action tag, with no payee-colored tags.
            # Exercises the compute_shares fallback to group_member_info.
            tag_dict = {
                "group_tag_id": self.running_config["test_group_id"]["test"]["id"],
                "action_tag": self.running_config["test_action_tag"],
            }
        else:
            raise ValueError(f"Unsupported scheme: {scheme}")

        tag_ids = self._flatten_values(tag_dict)
        tag_ids = [str(t) for t in tag_ids]
        await self.running.mm.set_transaction_tags(transaction_id, tag_ids)

    def _flatten_values(self, data):
        flattened = []
        if isinstance(data, (int, str)):
            flattened.append(data)
        elif isinstance(data, list):
            for item in data:
                flattened.extend(self._flatten_values(item))
        elif isinstance(data, dict):
            for value in data.values():
                flattened.extend(self._flatten_values(value))
        else:
            raise TypeError(f"Unsupported type: {type(data)}")
        return flattened

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def test_build_user_share_entries_names_present(self):
        """build_user_share_entries returns non-root payees plus the root payer."""
        transaction_id = self.created_transactions["split-child-repayer"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        result = await self.running.build_user_share_entries(transaction, self._group_member_info())

        expected_names = [m["Name"] for m in self.test_non_root] + [self.test_root["Name"]]
        actual_names = [user["name"] for user in result]
        self.assertCountEqual(actual_names, expected_names)

    async def test_build_user_share_entries_ids_match_names(self):
        """Returned userId values correspond to the correct Splitwise member."""
        transaction_id = self.created_transactions["split-child-repayer"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        result = await self.running.build_user_share_entries(transaction, self._group_member_info())

        name_to_id = {m["Name"]: m["id"] for m in self.test_non_root}
        name_to_id[self.test_root["Name"]] = self.test_root["id"]
        for user in result:
            self.assertEqual(user["userId"], name_to_id[user["name"]])

    async def test_build_user_share_entries_owed_share_values(self):
        """Non-root owed-shares are values calculate_shares would produce for the child amount."""
        transaction_id = self.created_transactions["split-child-repayer"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        result = await self.running.build_user_share_entries(transaction, self._group_member_info())

        expected_shares = set(self.running.calculate_shares(abs(SPLIT_CHILD_REPAYER_AMOUNT), NON_ROOT_COUNT))
        for user in result:
            if user["name"] == self.test_root["Name"]:
                continue  # root is the payer with owed-share=0 on a repayer child
            self.assertIn(user["owed-share"], expected_shares)

    async def test_build_user_share_entries_total_owed(self):
        """Total owed-shares across both split children sum to parent amount."""
        transaction_id = self.created_transactions["split-parent"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        result = await self.running.build_user_share_entries(transaction, self._group_member_info())
        total = sum(user["owed-share"] for user in result)
        self.assertAlmostEqual(total, abs(SPLIT_PARENT_AMOUNT), places=2)

    # ------------------------------------------------------------------
    # Refund flow (positive Monarch amount → reverse-roles Splitwise expense)
    # ------------------------------------------------------------------

    async def test_refund_non_split_satisfies_splitwise_invariants(self):
        """After to_refund_shares: sum(paid) == sum(owed) == cost."""
        transaction_id = self.created_transactions["refund-non-split"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        refund_shares, refund_cost = self.running.to_refund_shares(shares)

        self.assertAlmostEqual(sum(e["paid-share"] for e in refund_shares), refund_cost, places=2)
        self.assertAlmostEqual(sum(e["owed-share"] for e in refund_shares), refund_cost, places=2)

    async def test_refund_non_split_reverses_roles(self):
        """Root becomes sole ower; every other user becomes a payer with owed=0."""
        transaction_id = self.created_transactions["refund-non-split"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        refund_shares, _ = self.running.to_refund_shares(shares)

        for entry in refund_shares:
            if entry["name"] == self.test_root["Name"]:
                self.assertEqual(entry["paid-share"], 0)
                self.assertGreaterEqual(entry["owed-share"], 0)
            else:
                self.assertEqual(entry["owed-share"], 0)
                self.assertGreaterEqual(entry["paid-share"], 0)

    async def test_refund_non_split_cost_is_non_root_portion(self):
        """Refund cost equals the sum of non-root original owed-shares."""
        transaction_id = self.created_transactions["refund-non-split"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        expected_cost = sum(e["owed-share"] for e in shares if e["name"] != self.test_root["Name"])

        _, refund_cost = self.running.to_refund_shares(shares)
        self.assertAlmostEqual(refund_cost, expected_cost, places=2)

    # ------------------------------------------------------------------
    # Split with same payee in every child (Bug 1 regression)
    # ------------------------------------------------------------------

    async def test_split_same_payee_no_duplicate_user_ids(self):
        """Each userId appears exactly once — the invariant Splitwise enforces."""
        transaction_id = self.created_transactions["same-payee-split-parent"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        user_ids = [e["userId"] for e in shares]
        self.assertEqual(len(user_ids), len(set(user_ids)))

    async def test_split_same_payee_total_paid_equals_parent_cost(self):
        """sum(paid-share) == parent amount when root is the only payee in every split child."""
        transaction_id = self.created_transactions["same-payee-split-parent"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        total_paid = sum(e["paid-share"] for e in shares)
        self.assertAlmostEqual(total_paid, abs(SAME_PAYEE_PARENT_AMOUNT), places=2)

    async def test_split_same_payee_total_owed_equals_parent_cost(self):
        """Root's merged owed-share sums to the parent amount across both children."""
        transaction_id = self.created_transactions["same-payee-split-parent"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        total_owed = sum(e["owed-share"] for e in shares)
        self.assertAlmostEqual(total_owed, abs(SAME_PAYEE_PARENT_AMOUNT), places=2)

    # ------------------------------------------------------------------
    # Group-only tagging (no payee tags → even-split fallback)
    # ------------------------------------------------------------------

    async def test_group_only_falls_back_to_group_members(self):
        """Group tag with no payee tags → every group member gets an owed-share."""
        transaction_id = self.created_transactions["group-only"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        actual_names = {e["name"] for e in shares}
        expected_names = {self.test_root["Name"]} | {m["Name"] for m in self.test_non_root}
        self.assertEqual(actual_names, expected_names)

    async def test_group_only_owed_shares_sum_to_amount(self):
        """Fallback must still preserve the transaction cost invariant."""
        transaction_id = self.created_transactions["group-only"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)

        shares = await self.running.build_user_share_entries(transaction, self._group_member_info())
        total_owed = sum(e["owed-share"] for e in shares)
        self.assertAlmostEqual(total_owed, abs(GROUP_ONLY_AMOUNT), places=2)


if __name__ == "__main__":
    unittest.main(verbosity=10)
