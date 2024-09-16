import asyncio

import monarch_helper as mhelper
from monarchmoney import MonarchMoney

import splitwise_helper as shelper
from splitwise import Splitwise

import os
# import dotenv

import random
import yaml

class Main():
    
    def __init__(self):
        self.config = self.load_config()
        self.mm = asyncio.run(self.initialize_monarch())
        self.sw = self.initialize_splitwise()

        
    def load_config(self):
        if "isLambda" in os.environ:
            config = {}
            config['sw_consumer_key'] = os.getenv("sw_consumer_key")
            config['sw_consumer_secret'] = os.getenv("sw_consumer_secret")
            config['sw_api_key'] = os.getenv("sw_api_key")
        else:
            with open("config.yaml", 'r') as file:
                config = yaml.safe_load(file)
        return config 

    async def initialize_monarch(self):
        mm = MonarchMoney()
        mm = await mhelper.login(mm)
        return mm

    def initialize_splitwise(self):
        return Splitwise(self.config['sw_consumer_key'], 
                      self.config['sw_consumer_secret'], 
                      api_key=self.config['sw_api_key'])

    async def get_monarch_data(self): 
        '''
        Gather tag ID's.  Creates tag[{"Groupname":{"id":"tagid", "color": "tagcolor}, etc}]
        The application uses monarch tags to decipher who to charge.  
        Color represents user vs splitwise name
        '''
        original_tags = await self.mm.get_transaction_tags()
        tags = {}
        for tag in original_tags['householdTransactionTags']:
            tags[tag["name"]] = {"id": tag["id"], "color": tag["color"]}
        
        # Find tagged expenses with tag "Not in splitwise" transactions thare not pending
        includeTags = [tags["Not In Splitwise"]['id']]
        excludeTags = []
        # excludeTags = [tags["My Amount - Shared Expense"]['id']]
        transactions = await mhelper.get_transactions(self.mm, includeTags = includeTags, excludeTags=excludeTags, ignorePending=False)
        
        # From the transactions found, create an array contained detailed information of each transaction
        detailed_transactions = await mhelper.convert_transactions_to_parent_detailed_transactions(self.mm, transactions)
        return detailed_transactions, tags

    #Takes a detailed monarch transaction and calculates what each user owes
    async def calculate_sw_user_amount(self, transaction, group_member_info):    
        user_entry = [] #list of complete expense entries for a user
        names = [] # List of all names associated with a particular transaction
        counter = 0
        # Check if this object was split.  If so, then grab total price from original transaction
        if transaction['getTransaction']['hasSplitTransactions']:
            for transaction in transaction['getTransaction']['splitTransactions']:
                transaction =  await self.mm.get_transaction_details(transaction['id'])
                user_entry.append(await self.calculate_sw_user_amount(transaction, self.config['key_tag_colors'], group_member_info))
                ### Need additional code to combine users into just one entity
        else:
            for tag in transaction['getTransaction']['tags']:
                if tag['color'] == self.config['key_tag_colors']['payee']:
                    names.append(tag['name'])
                    counter += 1
            
            # creates an array of who owe's what.  When not easily divisible, the extra cent(s) are randomly assigned to an individual
            owed_share_array =  self.calculate_shares(transaction['getTransaction']['amount'] * -1, counter)
            
            for name, owed_share in zip(names, owed_share_array):
                paid_share = 0.00
                userId = None
                for member in group_member_info:
                    if member['first_name'] == name:
                        userId = member['memberId']
                        break
                if name == self.config['monarch_user_firstname']:
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
    def calculate_shares(self, money,n):
        q = round((round((money * 100), 0) // n) / 100, 2)  # quotient
        r = int(money * 100 % n)                  # remainder
        q1 = round(q + 0.01, 2)                   # quotient + 0.01
        result = [q1] * r + [q] * (n-r)
        return sorted(result, key=lambda x: random.random())       

    async def main(self):
        detailed_transactions, tags = await self.get_monarch_data()

        '''
        From here onwards, this is splitwise integration
        '''
        
        # Creates a dictionary of groups and their members
        # {Flirt Fund: {groupId: "XXXX", members: [{first_name: "XXXX", memberid: 000}, etc] }
        groups = {}
        original_groups = self.sw.getGroups()
        for group in original_groups:
            groups[group.name] = {"groupId": group.id, "members": []}
            for member in group.members:
                memberdic = {"first_name": member.first_name, "memberId": member.id}
                groups[group.name]['members'].append(memberdic)
        
        
        # compose expense information format
        '''
            users =  [{"name": "Alex",
                    "userId": 9999,
                    "paid-share": 100,
                    "owed-share": 20.0
                    },
                    ...]
        '''
        
        for transaction in reversed(detailed_transactions):
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
                groupId_info = await self.mm.get_transaction_details(child_transaction['id'])
            else:
                groupId_info = transaction
            for tag in groupId_info['getTransaction']['tags']:
                if tag['color'] == self.config['key_tag_colors']['splitwise-group']: # If the transaction tag matches a the splitwise group color
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
                expense_details['users'] = await self.calculate_sw_user_amount(transaction, group_member_info)
                    
                    
            '''
            Description/SW Title
            '''
            easy_descriptions = self.config['easy_descriptions']
            try:
                expense_details['description'] = easy_descriptions[transaction['getTransaction']['plaidName']] + " | " + groupId_info['getTransaction']['originalDate']
            except:
                expense_details['description'] = transaction['getTransaction']['plaidName'] + " | " + groupId_info['getTransaction']['originalDate']      
            
            expense_Id = None
            expense_Id = shelper.create_expense(self.sw,
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
                    modified_transaction =  await self.mm.get_transaction_details(modified)
                    transaction_tags = modified_transaction['getTransaction']['tags']
                    transaction_tags[:] = [d['id'] for d in transaction_tags if d.get('name') != "Not In Splitwise"]
                    transaction_tags.append(tags['In Splitwise']['id'])
                    await self.mm.set_transaction_tags(modified, transaction_tags)
            else:
                print(f'''ERROR with transaction !!!
                    
                    
                    {transaction}
                    
                    
                    {expense_details}''')

if __name__ == '__main__':
    running = Main()
    asyncio.run(running.main())