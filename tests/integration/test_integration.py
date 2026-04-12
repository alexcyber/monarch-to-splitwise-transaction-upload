"""
Integration tests for main.py — makes real API calls to Monarch Money.

Requirements:
  - Valid credentials in config.yaml (or environment variables)
  - The following additional fields in config.yaml:
      test_mon_account_id      : Monarch account ID for creating test transactions
      test_mon_category_id     : Monarch category ID used to tag test transactions
      test_sw_group_member_info: list of {Name, id, is_root} for the test SW group
      test_root_user           : list with single {id, Name} entry for the root user
      test_group_id            : dict {"test": {"id": <tag_id>}}
      test_action_tag          : tag ID for "Not In Splitwise"

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
        await self.create_non_split_transaction()
        await self.create_split_transaction()
        self.addAsyncCleanup(self.cleanup_created_transactions)

    async def cleanup_created_transactions(self):
        for transaction_id in self.created_transactions.values():
            is_deleted = await self.running.mm.delete_transaction(transaction_id)
            if not is_deleted:
                self.transactions_left.append(transaction_id)

    # ------------------------------------------------------------------
    # Transaction factory helpers
    # ------------------------------------------------------------------

    async def create_non_split_transaction(self):
        test_transac = await self.running.mm.create_transaction(
            date="2019-08-08",
            account_id=self.running_config["test_mon_account_id"],
            amount=1337.13,
            merchant_name="TEST_TRANSACTION",
            category_id=self.running_config["test_mon_category_id"],
            notes="TEST TRANSACTION - Not Split",
        )
        await self.set_test_tag_scheme(
            test_transac["createTransaction"]["transaction"]["id"],
            "not-split",
            [item["id"] for item in self.running_config["test_sw_group_member_info"]],
        )
        self.created_transactions["not-split"] = test_transac["createTransaction"]["transaction"]["id"]

    async def create_split_transaction(self):
        parent_total = -391.68
        split_amounts = [-78.34, -313.34]
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
            [item["id"] for item in self.running_config["test_sw_group_member_info"]],
        )
        await self.set_test_tag_scheme(
            child_repayer_id,
            "split-child-repayer",
            [item["id"] for item in self.running_config["test_sw_group_member_info"] if not item["is_root"]],
        )
        self.created_transactions["split-child-reimbursee"] = child_reimbursee_id
        self.created_transactions["split-child-repayer"] = child_repayer_id

    async def set_test_tag_scheme(self, transaction_id, scheme, group_member_ids):
        if scheme == "not-split":
            tag_dict = {
                "group_tag_id": self.running_config["test_group_id"]["test"]["id"],
                "payee": self.running_config["test_root_user"][0]["id"],
                "group_members": group_member_ids,
                "action_tag": self.running_config["test_action_tag"],
            }
        elif scheme == "split - parent":
            raise NotImplementedError("Split parent tag scheme not implemented")
        elif scheme == "split-child-reimbursee":
            tag_dict = {
                "group_tag_id": self.running_config["test_group_id"]["test"]["id"],
                "payee": self.running_config["test_root_user"][0]["id"],
                "action_tag": self.running_config["test_action_tag"],
            }
        elif scheme == "split-child-repayer":
            tag_dict = {
                "group_tag_id": self.running_config["test_group_id"]["test"]["id"],
                "group_members": group_member_ids,
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
        """build_user_share_entries returns all expected member names."""
        transaction_id = self.created_transactions["split-child-repayer"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [
            {"first_name": m["Name"], "memberId": m["id"]}
            for m in self.running_config["test_sw_group_member_info"]
        ]
        result = await self.running.build_user_share_entries(transaction, group_member_info)

        expected_names = [
            m["Name"]
            for m in self.running_config["test_sw_group_member_info"]
            if not m["is_root"]
        ]
        actual_names = [user["name"] for user in result]
        self.assertCountEqual(actual_names, expected_names)

    async def test_build_user_share_entries_ids_match_names(self):
        """Returned userId values correspond to the correct Splitwise member."""
        transaction_id = self.created_transactions["split-child-repayer"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [
            {"first_name": m["Name"], "memberId": m["id"]}
            for m in self.running_config["test_sw_group_member_info"]
        ]
        result = await self.running.build_user_share_entries(transaction, group_member_info)

        for user in result:
            expected_id = next(
                (m["id"] for m in self.running_config["test_sw_group_member_info"] if m["Name"] == user["name"]),
                None,
            )
            self.assertEqual(user["userId"], expected_id)

    async def test_build_user_share_entries_paid_share_values(self):
        """owed-share values for split-child-repayer are 78.33 or 78.34."""
        transaction_id = self.created_transactions["split-child-repayer"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [
            {"first_name": m["Name"], "memberId": m["id"]}
            for m in self.running_config["test_sw_group_member_info"]
        ]
        result = await self.running.build_user_share_entries(transaction, group_member_info)
        for user in result:
            self.assertIn(user["owed-share"], [78.33, 78.34])

    async def test_build_user_share_entries_total_paid_share(self):
        """Total owed-shares across both split children sum to 391.68."""
        transaction_id = self.created_transactions["split-parent"]
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [
            {"first_name": m["Name"], "memberId": m["id"]}
            for m in self.running_config["test_sw_group_member_info"]
        ]
        result = await self.running.build_user_share_entries(transaction, group_member_info)
        total = sum(user["owed-share"] for user in result)
        self.assertAlmostEqual(total, 391.68, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=10)
