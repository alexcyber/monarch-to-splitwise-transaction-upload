import asyncio

import monarch_helper as mhelper
from monarchmoney import MonarchMoney

import splitwise_helper as shelper
from splitwise import Splitwise

import os
import dotenv

import random

def load_config():
    dotenv.load_dotenv()
    sw_credentials = {}
    sw_credentials['sw_consumer_key'] = os.getenv("sw_consumer_key")
    sw_credentials['sw_consumer_secret'] = os.getenv("sw_consumer_secret")
    sw_credentials['sw_api_key'] = os.getenv("sw_api_key")
    return sw_credentials    
    

async def get_monarch_data(mm):
    #Initialize monarch money and login
    mm = MonarchMoney()
    await mhelper.login(mm)
    
    '''
    Gather tag ID's.  Creates tag[{"Groupname":{"id":"tagid", "color": "tagcolor}, etc}]
    The application uses monarch tags to decipher who to charge.  
    Color represents user vs splitwise name
    '''
    key_tag_colors = {'splitwise-group' : '#91DCEB',
                      'payee' : '#6E87F0',
                      'Not In Splitwise' : '#FF7369',
                      'In Splitwise': '#19D2A5'}
    original_tags = await mm.get_transaction_tags()
    tags = {}
    for tag in original_tags['householdTransactionTags']:
        tags[tag["name"]] = {"id": tag["id"], "color": tag["color"]}
    
    # Find tagged expenses with tag "Not in splitwise" transactions thare not pending
    includeTags = [tags["Not In Splitwise"]['id']]
    excludeTags = []
    # excludeTags = [tags["My Amount - Shared Expense"]['id']]
    transactions = await mhelper.get_transactions(mm, includeTags = includeTags, excludeTags=excludeTags, ignorePending=False)
    # mhelper.print_transactions(transactions)
    # print(len(transactions['allTransactions']['results'])) # Print how many transactions are included
    
    #From the transactions found, create an array contained detailed information of each transaction
    detailed_transactions = await mhelper.convert_transactions_to_parent_detailed_transactions(mm, transactions)
    # await mhelper.find_and_combine_transactions(mm,'188010689083774963',transactions)
    return detailed_transactions, key_tag_colors, tags

#Takes a detailed monarch transaction and calculates what each user owes
async def calculate_sw_user_amount(transaction, key_tag_colors, group_member_info, mm):    
    user_entry = [] #list of complete expense entries for a user
    names = [] # List of all names associated with a particular transaction
    counter = 0
    # Check if this object was split.  If so, then grab total price from original transaction
    if transaction['getTransaction']['hasSplitTransactions']:
        for transaction in transaction['getTransaction']['splitTransactions']:
            transaction =  await mm.get_transaction_details(transaction['id'])
            user_entry.append(await calculate_sw_user_amount(transaction, key_tag_colors, group_member_info, mm))
            ### Need additional code to combine users into just one entity
    else:
        for tag in transaction['getTransaction']['tags']:
            if tag['color'] == key_tag_colors['payee']:
                names.append(tag['name'])
                counter += 1
        
        owed_share_array =  calculate_shares(transaction['getTransaction']['amount'] * -1, counter)
        
        
        
        for name, owed_share in zip(names, owed_share_array):
            paid_share = 0.00
            userId = None
            for member in group_member_info:
                if member['first_name'] == name:
                    userId = member['memberId']
                    break
            if name == "Alex":
                if transaction['getTransaction']['isSplitTransaction']:
                    paid_share = transaction['getTransaction']['originalTransaction']['amount'] * -1
                else:
                    paid_share = transaction['getTransaction']['amount'] * -1 
            user_entry.append({"name": name,
                               "userId": userId,
                               "paid-share": paid_share,
                               "owed-share": owed_share
                               })
    
    flat_user_entry = []
    if type(user_entry[0]) is list:
        for xs in user_entry:
            for x in xs:
                flat_user_entry.append(x)
    else:
        flat_user_entry = user_entry
    return flat_user_entry

# Calculates the amount each person owes    
def calculate_shares(money,n):
    q = round((round((money * 100), 0) // n) / 100, 2)  # quotient
    r = int(money * 100 % n)                  # remainder
    q1 = round(q + 0.01, 2)                   # quotient + 0.01
    result = [q1] * r + [q] * (n-r)
    return sorted(result, key=lambda x: random.random())       

async def main():
    
    mm = MonarchMoney()
    await mhelper.login(mm)
    
    detailed_transactions, key_tag_colors, tags = await get_monarch_data(mm)

    '''
    From here onwards, this is splitwise integration
    '''
    
    # Creates a dictionary of groups and their members
    # {Flirt Fund: {groupId: "XXXX", members: [{first_name: "XXXX", memberid: 000}, etc] }
    sw_credentials=load_config()
    sw =Splitwise(sw_credentials['sw_consumer_key'], 
                  sw_credentials['sw_consumer_secret'], 
                  api_key=sw_credentials['sw_api_key'])
    groups = {}
    original_groups = sw.getGroups()
    for group in original_groups:
        groups[group.name] = {"groupId": group.id, "members": []}
        for member in group.members:
            memberdic = {"first_name": member.first_name, "memberId": member.id}
            groups[group.name]['members'].append(memberdic)
    
    
    # compose expense information format
    '''
        users =  [{"name": "Alex",
                   "userId": 28199,
                   "paid-share": 100,
                   "owed-share": 20.0
                   },
                ...]
    '''

    
    '''
    Temp line
    '''
    #Single Entry
    # detailed_transactions = [{'getTransaction': {'id': '185591663350027360', 'amount': -143.99, 'pending': False, 'isRecurring': True, 'date': '2024-08-08', 'originalDate': '2024-08-08', 'hideFromReports': False, 'needsReview': False, 'reviewedAt': None, 'reviewedByUser': None, 'plaidName': 'PUGET SOUND ENERGY INC 8882255773 WA', 'notes': None, 'hasSplitTransactions': False, 'isSplitTransaction': False, 'isManual': False, 'splitTransactions': [], 'originalTransaction': None, 'attachments': [], 'account': {'id': '164782108102923413', 'displayName': 'Citi Double Cash Card (...5839)', 'logoUrl': 'https://api.monarchmoney.com/cdn-cgi/image/width=128/images/institution/75111197916293981', 'mask': '5839', 'subtype': {'display': 'Credit Card', '__typename': 'AccountSubtype'}, '__typename': 'Account'}, 'category': {'id': '164780499636622560', '__typename': 'Category'}, 'goal': None, 'merchant': {'id': '169404276032968665', 'name': 'Puget Sound Energy', 'transactionCount': 8, 'logoUrl': 'https://res.cloudinary.com/monarch-money/image/authenticated/s--e6vdkz2z--/c_thumb,h_132,w_132/v1/production/merchant_logos/provider/MCH-b848a1c0-f1a1-b4c6-7b35-69bec5e0c1fc_ajvzon', 'recurringTransactionStream': {'id': '177093911657878652', '__typename': 'RecurringTransactionStream'}, '__typename': 'Merchant'}, 'tags': [{'id': '187656425668908411', 'name': 'Not In Splitwise', 'color': '#FF7369', 'order': 4, '__typename': 'TransactionTag'}, {'id': '164780499603068103', 'name': 'Their Amount - Shared Expense', 'color': '#F0648C', 'order': 1, '__typename': 'TransactionTag'}, {'id': '188004390170301969', 'name': 'Justin', 'color': '#6E87F0', 'order': 7, '__typename': 'TransactionTag'}, {'id': '188005411499054762', 'name': 'test', 'color': '#91DCEB', 'order': 10, '__typename': 'TransactionTag'}, {'id': '188006571569092387', 'name': 'Roy', 'color': '#6E87F0', 'order': 9, '__typename': 'TransactionTag'}, {'id': '188006554659755809', 'name': 'Jewel', 'color': '#6E87F0', 'order': 8, '__typename': 'TransactionTag'}, {'id': '188004120976725480', 'name': 'Laurel', 'color': '#6E87F0', 'order': 6, '__typename': 'TransactionTag'}, {'id': '188017050885592410', 'name': 'Alex', 'color': '#6E87F0', 'order': 12, '__typename': 'TransactionTag'}], 'needsReviewByUser': None, '__typename': 'Transaction'}, 'myHousehold': {'users': [{'id': '164780499553446446', 'name': 'Alex Molina', '__typename': 'User'}], '__typename': 'Household'}}]
    #Split Entry
    # detailed_transactions = [{'getTransaction': {'id': '185517026045891686', 'amount': -85.0, 'pending': False, 'isRecurring': True, 'date': '2024-08-07', 'originalDate': '2024-08-07', 'hideFromReports': False, 'needsReview': True, 'reviewedAt': None, 'reviewedByUser': None, 'plaidName': 'ZIPLY FIBER * INTERNET 866-699-4759 WA', 'notes': None, 'hasSplitTransactions': True, 'isSplitTransaction': False, 'isManual': False, 'splitTransactions': [{'id': '188010689083774962', 'amount': -17.0, 'merchant': {'id': '164782157222418054', 'name': 'Ziply Fiber', '__typename': 'Merchant'}, 'category': {'id': '164780499636622561', 'name': 'Internet & Cable', '__typename': 'Category'}, '__typename': 'Transaction'}, {'id': '188010689083774963', 'amount': -68.0, 'merchant': {'id': '164782157222418054', 'name': 'Ziply Fiber', '__typename': 'Merchant'}, 'category': {'id': '164780499636622561', 'name': 'Internet & Cable', '__typename': 'Category'}, '__typename': 'Transaction'}], 'originalTransaction': None, 'attachments': [], 'account': {'id': '164782108102923413', 'displayName': 'Citi Double Cash Card (...5839)', 'logoUrl': 'https://api.monarchmoney.com/cdn-cgi/image/width=128/images/institution/75111197916293981', 'mask': '5839', 'subtype': {'display': 'Credit Card', '__typename': 'AccountSubtype'}, '__typename': 'Account'}, 'category': {'id': '164780499636622561', '__typename': 'Category'}, 'goal': None, 'merchant': {'id': '164782157222418054', 'name': 'Ziply Fiber', 'transactionCount': 20, 'logoUrl': 'https://res.cloudinary.com/monarch-money/image/authenticated/s--cLOUARH6--/c_thumb,h_132,w_132/v1/production/merchant_logos/provider/MCH-c87f7b19-4f2c-447e-a137-c2edb0396f40_eyxz9m', 'recurringTransactionStream': {'id': '164782279828215267', '__typename': 'RecurringTransactionStream'}, '__typename': 'Merchant'}, 'tags': [{'id': '187656425668908411', 'name': 'Not In Splitwise', 'color': '#FF7369', 'order': 4, '__typename': 'TransactionTag'}, {'id': '164780499603068103', 'name': 'Their Amount - Shared Expense', 'color': '#F0648C', 'order': 1, '__typename': 'TransactionTag'}, {'id': '188004390170301969', 'name': 'Justin', 'color': '#6E87F0', 'order': 7, '__typename': 'TransactionTag'}, {'id': '188006571569092387', 'name': 'Roy', 'color': '#6E87F0', 'order': 9, '__typename': 'TransactionTag'}, {'id': '188006554659755809', 'name': 'Jewel', 'color': '#6E87F0', 'order': 8, '__typename': 'TransactionTag'}, {'id': '188004120976725480', 'name': 'Laurel', 'color': '#6E87F0', 'order': 6, '__typename': 'TransactionTag'}], 'needsReviewByUser': None, '__typename': 'Transaction'}, 'myHousehold': {'users': [{'id': '164780499553446446', 'name': 'Alex Molina', '__typename': 'User'}], '__typename': 'Household'}}]
    '''
    /Temp line
    '''
    
    
    for transaction in reversed(detailed_transactions):
        
        # print(transaction)
        # print("\n")
        expense_details = {
                        "modified_transactions": [transaction['getTransaction']['id']],
                        "description" : None,
                        "cost": None,
                        "groupId": {'name': None,
                                    'id': None
                                    },
                        "users": []}
       
        # Add additional monarch id's that will be modified if they exist
        if transaction['getTransaction']['hasSplitTransactions']:
            for child in transaction['getTransaction']['splitTransactions']:
                expense_details['modified_transactions'].append(child['id'])
        
        '''
        Cost, each user amount owed, description, and group id are required.  Each section is labelled 
        '''
        
        '''
        groupId
        - Pulls the monarch tag that contains the SW group name.  Add SW groupID to expense_details
        - Once the group has been identified, pull SW memberId's to be used when assigning individual expenses 
        '''
        group_member_info = None
        # If the transaction has been split, take the groupId of the first child object.
        # This is because the parent object cannot be edited once split.  Child's can be
        if transaction['getTransaction']['hasSplitTransactions']:
            child_transaction = transaction['getTransaction']['splitTransactions'][0]
            groupId_info = await mm.get_transaction_details(child_transaction['id'])
        else:
            groupId_info = transaction
        for tag in groupId_info['getTransaction']['tags']:
            if tag['color'] == key_tag_colors['splitwise-group']: # If the transaction tag matches a the splitwise group color
                for key, value in groups.items(): # Iterate through SW groups
                    if key == tag['name']: # If SW group name matches Monarch tag
                        expense_details['groupId']['id'] = value['groupId'] # Add SW groupID to expense_details
                        expense_details['groupId']['name'] = key
                        group_member_info = value['members'] # Variable contains the SW group member names and ID's
                        continue
            
        '''
        Cost
        '''
        expense_details['cost'] = transaction['getTransaction']['amount'] * -1
        
        '''
        Calculate each user amount
        '''
        # If SW group member info was found
        if group_member_info:
            expense_details['users'] = await calculate_sw_user_amount(transaction, key_tag_colors, group_member_info, mm)
                
                
        '''
        Description/SW Title
        '''
        easy_descriptions = {"City of Redmond Redmond WA": "Water Bill",
                          "ZIPLY FIBER INTERNET 866-699-4759 WA": "Internet",
                          "WASTE MGMT WM EZPAY HOUSTON TX": "Garbage",
                          "PUGET SOUND ENERGY INC 8882255773 WA": "Electricity"}
        try:
            expense_details['description'] = easy_descriptions[transaction['getTransaction']['plaidName']] + " | " + groupId_info['getTransaction']['originalDate']
        except:
            expense_details['description'] = transaction['getTransaction']['plaidName'] + " | " + groupId_info['getTransaction']['originalDate']      
        
        '''
        Verify Correct Expense format and create expense
        '''
        
        expense_Id = None
        expense_Id = shelper.create_expense(sw,
                                            expense_details['description'],
                                            expense_details['cost'],
                                            expense_details['groupId']['id'],
                                            expense_details['users'])
    
        '''
        This part double checks SW entry and alters monarch tags to show the transaction has been processed
        '''
        if expense_Id:
            print(f"""Successfully created a transaction with the following details: 
                  Expense Description: {expense_details['description']}
                  Expense Cost: {expense_details['cost']}
                  Group: {expense_details['groupId']['name']}""")
            for modified in expense_details['modified_transactions']:
                modified_transaction =  await mm.get_transaction_details(modified)
                transaction_tags = modified_transaction['getTransaction']['tags']
                transaction_tags[:] = [d['id'] for d in transaction_tags if d.get('name') != "Not In Splitwise"]
                transaction_tags.append(tags['In Splitwise']['id'])
                await mm.set_transaction_tags(modified, transaction_tags)
        else:
            print(f'''ERROR with transaction !!!
                  
                  
                  {transaction}
                  
                  
                  {expense_details}''')

        
        

    


asyncio.run(main())

