from monarchmoney import MonarchMoney
import asyncio
import json
import os
import time

async def login(mm, credentials, uuid):
    try:
        mm.load_session()
        # Immediately test if session is valid
        try:
            await mm.get_accounts()
            return mm
        except Exception:
            raise ValueError("Invalid session, need to re-login.")
    except FileNotFoundError:
        os.makedirs(".mm", exist_ok=True)
    except ValueError:
        if os.path.exists(".mm/mm_session.pickle"):
            os.remove(".mm/mm_session.pickle")
        del mm._headers["Authorization"]
    
    # Login if session is either invalid or doesn't exist
    mm._headers['Device-UUID'] = uuid # See https://github.com/hammem/monarchmoney/issues/137 for additional information
    await mm.login(
        email=credentials['username'],
        password=credentials['password'],
        save_session=True,
        use_saved_session=False
    )
    return mm


async def get_tags(mm):
    return await mm.get_transaction_tags()


def print_transactions(transactions):
    for transaction in transactions['allTransactions']['results']:
        print(f'Transaction Name: {transaction['plaidName']}')
        print(f'Date: {transaction['date']}')
        for tag in transaction['tags']:
            print(tag['name'])
        print('\n')

    
async def get_transactions(mm, includeTags=[], excludeTags=[], limit=100, ignorePending=False):
    transactions = await mm.get_transactions(tag_ids=includeTags, limit=limit)
    
    for transaction in transactions['allTransactions']['results'][:]:
        
        # if we are to ignore pending
        if ignorePending:
            if transaction['pending'] == False:
                transactions['allTransactions']['results'].remove(transaction)
                continue
        
        # remove excluded tags
        # Here's some bad code, maybe fix later
        for tag in excludeTags:
            for transaction_tag in transaction['tags']:
                if tag in transaction_tag['id']:
                    transactions['allTransactions']['results'].remove(transaction) 
                    continue

    transactions['allTransactions']['totalCount'] = len(transactions['allTransactions']['results'])
    return transactions

async def convert_transactions_to_parent_detailed_transactions(mm, lite_transactions):
    detailed_transactions = []
    transaction_id_set = set()

    for transaction in lite_transactions['allTransactions']['results']:
        
        transactionId = transaction['id']
        if transactionId in transaction_id_set:
            continue
        detailed_transaction = await mm.get_transaction_details(transactionId)
        
        # If a split transaction, find the parent transactionID within the object and gather the details of the parent.
        # Child object is not saved directly.  Parent has Child object information
        if transaction['isSplitTransaction']:
            transactionId = detailed_transaction['getTransaction']['originalTransaction']['id']
            if transactionId in transaction_id_set:
                continue
            detailed_transaction = await mm.get_transaction_details(transactionId)
        
        detailed_transactions.append(detailed_transaction)    
        transaction_id_set.add(str(detailed_transaction['getTransaction']['id']))
    
    return detailed_transactions