import unittest
from unittest.mock import patch
import os
import sys
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unit_tests.test_data_access as test_data
from main import Main

class TestMain(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        '''First method to run before any tests are executed'''
        cls.running = Main()
        cls.running_config = cls.running.load_config()
        cls.created_transactions = {}


    @classmethod
    def tearDownClass(cls):
        '''Last method to run after all tests have completed'''
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(cls._async_tear_down())
        finally:
            # Cancel all pending tasks before closing the loop
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
    
    
    @classmethod
    async def _async_tear_down(cls):
        '''Deletes all test transactions, even if they were not created by the test.  Runs once after all tests have completed'''
        test_category_id = cls.running_config['test_mon_category_id']
        transactions = await cls.running.mm.get_transactions(category_ids=[test_category_id])
        for transaction in transactions['allTransactions']['results']:
            await cls.running.mm.delete_transaction(transaction['id'])


    async def asyncSetUp(self):
        '''Orchestrates the creation of test transactions'''
        await self.create_non_split_transaction()
        await self.create_split_transaction()
        self.addAsyncCleanup(self.cleanup_created_transactions)
        
        
    async def cleanup_created_transactions(self):
        '''Deletes registered test transactions.  Runs after every test'''
        transactions_left = []
        for transaction_id in self.created_transactions.values():
            is_deleted = await self.running.mm.delete_transaction(transaction_id)
            if not is_deleted:
                transactions_left.append(transaction_id)
        self.created_transactions = transactions_left


    async def create_non_split_transaction(self):
        '''Create a non-split test transaction.  Currently hardcoded to a specific amount'''
        test_transac = await self.running.mm.create_transaction(
            date = "2019-08-08",
            account_id = self.running_config['test_mon_account_id'],
            amount = 1337.13,
            merchant_name = 'TEST_TRANSACTION',
            category_id = self.running_config['test_mon_category_id'],
            notes = "TEST TRANSACTION - Not Split"
        )
        await self.set_test_tag_scheme(test_transac['createTransaction']['transaction']['id'], 'not-split')
        self.created_transactions['not-split'] = test_transac['createTransaction']['transaction']['id']


    async def create_split_transaction(self):
        '''Create a non-split test transaction.  Currently hardcoded to a specific amount'''
        parent_total = -391.68
        split_amounts = [-78.34, -313.34]
        tolerance = 1e-2

        # Ensure the split amounts add up to the parent total
        # assert sum(split_amounts) == parent_total, "Split amounts do not add up to the parent total"

        # Common transaction details
        date = "2019-08-09"
        account_id = self.running_config['test_mon_account_id']
        merchant_name = "TEST_TRANSACTION"
        category_id = self.running_config['test_mon_category_id']
        notes = "Split transaction -"

        # Create the parent transaction
        parent_transaction = await self.running.mm.create_transaction(
            date = date,
            account_id = self.running_config['test_mon_account_id'],
            amount = parent_total,
            merchant_name = merchant_name,
            category_id=category_id,
            notes= notes + " Parent"
        )

        parent_transaction_id = parent_transaction["createTransaction"]["transaction"]["id"]
        self.created_transactions['split-parent'] = parent_transaction_id

        transactions = await self.running.mm.get_transactions(category_ids=["199976039533811467"])
        ## TAG Parent required
        # assert 78.34 + 313.34 == parent_total, "Split amounts do not add up to the parent total"
        assert abs(sum(split_amounts) - parent_total) < tolerance, "Split amounts do not add up to the parent total"

        # Prepare split data
        split_data = [
            {
                "merchantName": merchant_name,
                "amount": split_amounts[0],
                "categoryId": str(category_id)
            },
            {
                "merchantName": merchant_name,
                "amount": split_amounts[1],
                "categoryId": str(category_id)
            }
        ]
        
        # Update the parent transaction with the split data
        parent_transaction = await self.running.mm.update_transaction_splits(
            transaction_id=parent_transaction_id,
            split_data=split_data
        )
        
        # Get the child transaction IDs
        child_reimbursee_transaction_id = parent_transaction['updateTransactionSplit']['transaction']['splitTransactions'][0]['id']
        child_repayer_transaction_id = parent_transaction['updateTransactionSplit']['transaction']['splitTransactions'][1]['id']
        
        # Set the tag scheme for the child transactions
        await self.set_test_tag_scheme(child_reimbursee_transaction_id, 'split-child-reimbursee')
        await self.set_test_tag_scheme(child_repayer_transaction_id, 'split-child-repayer')
        
        # Store the child transaction IDs
        self.created_transactions['split-child-reimbursee'] = child_reimbursee_transaction_id
        self.created_transactions['split-child-repayer'] = child_repayer_transaction_id
        
        
    async def set_test_tag_scheme(self, transaction_id, scheme):
        if scheme == "not-split":
            tag_dict = {
                'group_tag_id': self.running_config['test_group_id']['test']['id'],
                'payee': self.running_config['test_reimbursee_id'][0]['id'],
                'group_members': [item['id'] for item in self.running_config['test_repayer_ids']],
                'action_tag': self.running_config['test_action_tag']
            }
        elif scheme == "split - parent":
            raise NotImplementedError("Split parent tag scheme not implemented")
        elif scheme == "split-child-reimbursee":
            tag_dict = {
                'group_tag_id': self.running_config['test_group_id']['test']['id'],
                'payee': self.running_config['test_reimbursee_id'][0]['id'],
                'action_tag': self.running_config['test_action_tag']
            }
        elif scheme == "split-child-repayer":
            tag_dict = {
                'group_tag_id': self.running_config['test_group_id']['test']['id'],
                'group_members': [item['id'] for item in self.running_config['test_repayer_ids']],
                'action_tag': self.running_config['test_action_tag']
            }
        else:
            raise ValueError(f"Unsupported scheme: {scheme}")
        
        # Flatten dictionary values
        tag_ids = self.flatten_values(tag_dict)
        for i, tag in enumerate(tag_ids):
            tag_ids[i] = str(tag)
        tag_update = await self.running.mm.set_transaction_tags(transaction_id, tag_ids)


    def flatten_values(self, data):
        flattened = []

        if isinstance(data, (int, str)):
            flattened.append(data)
        elif isinstance(data, list):
            for item in data:
                flattened.extend(self.flatten_values(item))
        elif isinstance(data, dict):
            for value in data.values():
                flattened.extend(self.flatten_values(value))
        else:
            raise TypeError(f"Unsupported type: {type(data)}")

        return flattened
        
        
    @patch.dict(os.environ, {
        'sw_consumer_key': 'test_consumer_key',
        'sw_consumer_secret': 'test_consumer_secret',
        'sw_api_key': 'test_api_key',
        'isLambda': 'True'
    }, clear=True)
    async def test_load_config_new(self):
        expected_config = {
            'sw_consumer_key': 'test_consumer_key',
            'sw_consumer_secret': 'test_consumer_secret',
            'sw_api_key': 'test_api_key'
        }
        test_config = self.running.load_config()
        self.assertEqual(test_config, expected_config)


    async def test_calculate_shares_uneven_split_1(self):
        money = 391.68
        n = 5
        expected_result = [78.33, 78.34]
        result = self.running.calculate_shares(money, n)
        self.assertAlmostEqual(sum(result), money, places=2)
        self.assertEqual(len(result), n)
        self.assertTrue(all(share in expected_result for share in result))
    
    async def test_calculate_shares_uneven_split_2(self):
        money = 313.34
        n = 4
        expected_result = [78.33, 78.34]
        result = self.running.calculate_shares(money, n)
        self.assertAlmostEqual(sum(result), money, places=2)
        self.assertEqual(len(result), n)
        self.assertTrue(all(share in expected_result for share in result))


    async def test_calculate_shares_even_split(self):
        money = 12.00
        n = 3
        result = self.running.calculate_shares(money, n)
        self.assertEqual(sum(result), money)
        self.assertEqual(len(result), n)
        self.assertTrue(all(share in [4.00] for share in result))
        

    async def test_calculate_sw_user_amount_names_present(self):
        transaction_id = self.created_transactions['split-child-repayer']
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [{'first_name': m['Name'], 'memberId': m['id']} for m in self.running_config['test_repayer_ids']]

        result = await self.running.calculate_sw_user_amount(transaction, group_member_info)

        expected_names = [m['Name'] for m in self.running_config['test_repayer_ids']]
        actual_names = [user['name'] for user in result]

        self.assertCountEqual(actual_names, expected_names)
        
    async def test_calculate_sw_user_amount_ids_match_names(self):
        transaction_id = self.created_transactions['split-child-repayer']
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [{'first_name': m['Name'], 'memberId': m['id']} for m in self.running_config['test_repayer_ids']]

        result = await self.running.calculate_sw_user_amount(transaction, group_member_info)

        for user in result:
            expected_id = next((m['id'] for m in self.running_config['test_repayer_ids'] if m['Name'] == user['name']), None)
            self.assertEqual(user['userId'], expected_id)

    async def test_calculate_sw_user_amount_paid_share_values(self):
        transaction_id = self.created_transactions['split-child-repayer']
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [{'first_name': m['Name'], 'memberId': m['id']} for m in self.running_config['test_repayer_ids']]

        result = await self.running.calculate_sw_user_amount(transaction, group_member_info)

        for user in result:
            self.assertIn(user['owed-share'], [78.33, 78.34])

    async def test_calculate_sw_user_amount_total_paid_share(self):
        transaction_id = self.created_transactions['split-parent']
        transaction = await self.running.mm.get_transaction_details(transaction_id)
        group_member_info = [{'first_name': m['Name'], 'memberId': m['id']} for m in self.running_config['test_repayer_ids']]

        result = await self.running.calculate_sw_user_amount(transaction, group_member_info)

        total = sum(user['owed-share'] for user in result)
        self.assertAlmostEqual(total, 391.68, places=2)


if __name__ == '__main__':
    unittest.main(verbosity=10)
