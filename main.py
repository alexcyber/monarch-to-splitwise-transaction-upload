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
        if "isLambda" in os.environ and os.environ['isLambda']:
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
        uuid = self.config['monarch_device_uuid']
        credentials = {"username": self.config['monarch_user_email'],
                       "password": self.config['monarch_user_password']}
        mm = await mhelper.login(mm, credentials, uuid)
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
    
    async def build_user_share_entries(self, transaction, group_member_info):
        '''Build the final list of per-user paid/owed shares for a transaction.

        Walks the transaction (or each of its split children), delegates owed-share
        computation to compute_shares, merges duplicate users, and assigns the full
        paid-share to the root user — the single payer Splitwise requires.  Guarantees
        exactly one entry per user and sum(paid-share) == transaction cost.'''
        user_shares = [] # list of complete expense entries a set of user_shares
        # Check if this object was split.  If so, then grab total price from original transaction
        if transaction['getTransaction']['hasSplitTransactions']:
            for transaction_child in transaction['getTransaction']['splitTransactions']:
                transaction_child = await self.mm.get_transaction_details(transaction_child['id'])
                user_shares.append(await self.compute_shares(transaction_child, group_member_info)) # compute on a per split basis
        else:
            user_shares.append(await self.compute_shares(transaction, group_member_info)) # compute as a whole
        user_shares = self.flatten_list(user_shares)
        user_shares = self.merge_user_shares(user_shares)

        # Splitwise requires a payer. Root user holds the transaction on their account,
        # so they are always the payer of the full amount. Update existing entry or inject.
        root_user_name = self.config['monarch_user_firstname']
        total_amount = abs(transaction['getTransaction']['amount'])
        root_entry = next((e for e in user_shares if e['name'] == root_user_name), None)
        if root_entry:
            root_entry['paid-share'] = total_amount
        else:
            root_user_id = next(
                (m['memberId'] for m in group_member_info if m['first_name'] == root_user_name),
                None,
            )
            user_shares.append({
                "name": root_user_name,
                "userId": root_user_id,
                "paid-share": total_amount,
                "owed-share": 0,
            })

        return user_shares

    def flatten_list(self,nested_list):
        flat = []
        for item in nested_list:
            if isinstance(item, list):
                flat.extend(self.flatten_list(item))  # recursive flattening
            else:
                flat.append(item)
        return flat

    def to_refund_shares(self, user_shares):
        '''Transform normal-expense shares into refund-expense shares.

        Semantics: a refund lands on root user's account. Only the non-root portion
        of the refund belongs on the group ledger — root's own share simply returns
        to them personally. In the resulting Splitwise expense the non-root payees
        become "payers" (their debt decreases by their share of the refund) and
        root becomes the sole "ower" of that reduced cost.

        Example: $20 refund, original 70/30 split (root paid) →
            Root:   paid=0,  owed=6     (non-root total)
            Friend: paid=6,  owed=0
            cost = 6

        Done in integer cents (same convention as calculate_shares) to guarantee
        no float drift.  Only converts back to dollars at the output boundary.

        Returns (new_shares, new_cost).'''
        root_user_name = self.config['monarch_user_firstname']
        new_shares = []
        new_cost_cents = 0
        for entry in user_shares:
            paid_cents = int(round(entry['paid-share'] * 100))
            owed_cents = int(round(entry['owed-share'] * 100))
            if entry['name'] == root_user_name:
                new_owed_cents = paid_cents - owed_cents
                new_shares.append({**entry, 'paid-share': 0, 'owed-share': round(new_owed_cents / 100, 2)})
                new_cost_cents += new_owed_cents
            else:
                new_shares.append({**entry, 'paid-share': round(owed_cents / 100, 2), 'owed-share': 0})
        return new_shares, round(new_cost_cents / 100, 2)

    def merge_user_shares(self, user_shares):
        '''Consolidate entries by userId, summing paid-share and owed-share.

        Splitwise rejects an expense if the same user appears twice, so any path that
        can produce duplicates (e.g. a payee tagged in multiple split children) must
        funnel through here before the shares are submitted.'''
        merged = {}
        for entry in user_shares:
            uid = entry['userId']
            if uid in merged:
                merged[uid]['paid-share'] = round(merged[uid]['paid-share'] + entry['paid-share'], 2)
                merged[uid]['owed-share'] = round(merged[uid]['owed-share'] + entry['owed-share'], 2)
            else:
                merged[uid] = dict(entry)
        return list(merged.values())

    async def compute_shares(self, transaction, group_member_info):
        '''Compute the owed-share distribution for a single transaction (or split child).

        Reads payee-colored tags to decide who owes, then uses calculate_shares to
        divide the amount evenly (cent-precise).  If no payee tags are present, falls
        back to an even split across every member of group_member_info.  paid-share
        is deliberately left at 0 — assigning it is the caller's responsibility so
        that callers aggregating over multiple children don't end up double-counting.'''
        # List of all names associated with a particular transaction
        names = [
            tag['name']
            for tag in transaction['getTransaction']['tags']
            if tag['color'] == self.config['key_tag_colors']['payee']
        ]
        if not names and group_member_info:
            names = [m['first_name'] for m in group_member_info]

        amount = abs(transaction['getTransaction']['amount'])
        # creates an array of who owe's what.  When not easily divisible, the extra cent(s) are randomly assigned to an individual
        owed_share_array = self.calculate_shares(amount, len(names))

        user_entry = [] # list of complete expense entries for a user
        for name, owed_share in zip(names, owed_share_array):
            userId = next(
                (m['memberId'] for m in group_member_info if m['first_name'] == name),
                None,
            )
            user_entry.append({
                "name": name,
                "userId": userId,
                "paid-share": 0.00,
                "owed-share": owed_share,
            })
        return user_entry

    
    
    # Calculates the amount each person owes    
    def calculate_shares(self, money, n):
        money_cents = int(round(money * 100,0))
        lower_bound_cents = int(money_cents // n)
        upper_bound_cents = lower_bound_cents + 1
        remaining_cents = money_cents - (n * lower_bound_cents)
        result = [lower_bound_cents] * (n - remaining_cents) + [upper_bound_cents] * remaining_cents
        result =  [round(x / 100, 2) for x in result]
        return sorted(result, key=lambda x: random.random())


    async def get_groupId_transaction(self, transaction):
        '''Determines which transaction to use for SW group information'''
        if transaction['getTransaction']['hasSplitTransactions']:
                child_transaction = transaction['getTransaction']['splitTransactions'][0]
                groupId_transaction = await self.mm.get_transaction_details(child_transaction['id'])
        else:
            groupId_transaction = transaction
        return groupId_transaction
    
    
    async def get_group_metadata(self, groups, transaction):
        '''For a specific SW group tag, get id, name, transaction  and members'''
        # If the transaction has been split, take the groupId of the first child object.
        # This is because the parent object cannot be edited once split.  Child's can be
        groupId_transaction = await self.get_groupId_transaction(transaction)
        tags = groupId_transaction['getTransaction'].get('tags', [])
        if not tags:
            raise ValueError(
                f"No tags found for transaction ID {groupId_transaction['getTransaction'].get('id')}. "
                f"Transaction data: {groupId_transaction['getTransaction']}"
            )

        sw_group_color = self.config['key_tag_colors']['splitwise-group']
        for tag in tags:
            if tag.get('color') == sw_group_color: # If the transaction tag matches a the splitwise group color
                group = groups.get(tag.get('name'))
                if group: # If SW group name matches Monarch tag
                    group_id = group['groupId'] # Add SW groupID to expense_details
                    group_name = tag['name']
                    group_member_info = group['members'] # Variable contains the SW group member names and ID's
                    return group_id, group_name, group_member_info, groupId_transaction
        # If no matching group found, return None values
        return None, None, None, groupId_transaction
              
                    
    def get_sw_groups(self):
        '''Get splitwise group information'''
        # Creates a dictionary of groups and their members
        # {Flirt Fund: {groupId: "XXXX", members: [{first_name: "XXXX", memberid: 000}, etc] }
        groups = {}
        original_groups = self.sw.getGroups()
        for group in original_groups:
            groups[group.name] = {"groupId": group.id, "members": []}
            for member in group.members:
                memberdic = {"first_name": member.first_name, "memberId": member.id}
                groups[group.name]['members'].append(memberdic)
        return groups


    async def main(self):
        detailed_transactions, tags = await self.get_monarch_data()

        '''
        From here onwards, this is splitwise integration
        '''
        
        # Creates a dictionary of groups and their members
        # {Flirt Fund: {groupId: "XXXX", members: [{first_name: "XXXX", memberid: 000}, etc] }
        groups = self.get_sw_groups()
        
        
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
            expense_details['groupId']['id'], expense_details['groupId']['name'], group_member_info, groupId_transaction = await self.get_group_metadata(groups, transaction)
            if not groupId_transaction:
                raise KeyError(
                    f"Failed to pull SW group metadata"
                )

            '''
            Cost
            Positive Monarch amount = refund/income; flip to a reverse-roles Splitwise
            expense so the correct party's debt decreases.  Zero-amount transactions
            are almost always a stray tag and get skipped.
            '''
            raw_amount = transaction['getTransaction']['amount']
            is_refund = raw_amount > 0
            expense_details['cost'] = abs(raw_amount)
            if expense_details['cost'] == 0:
                print(f"SKIPPING $0 transaction (tag likely in error): "
                      f"{transaction['getTransaction']['plaidName']} | {transaction['getTransaction']['date']}")
                continue

            '''
            Calculate each user amount
            '''
            # If SW group member info was found
            if group_member_info:
                expense_details['users'] = await self.build_user_share_entries(transaction, group_member_info)
                if is_refund:
                    expense_details['users'], expense_details['cost'] = self.to_refund_shares(expense_details['users'])
                    if expense_details['cost'] == 0:
                        print(f"SKIPPING refund where only root user was tagged (no group balance change): "
                              f"{transaction['getTransaction']['plaidName']} | {transaction['getTransaction']['date']}")
                        continue
                    
            '''
            Description/SW Title
            '''
            easy_descriptions = self.config['easy_descriptions']
            try:
                expense_details['description'] = easy_descriptions[transaction['getTransaction']['plaidName']] + " | " + groupId_transaction['getTransaction']['originalDate']
            except:
                expense_details['description'] = transaction['getTransaction']['plaidName'] + " | " + groupId_transaction['getTransaction']['originalDate']      
            
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
                expense_type = "refund" if is_refund else "expense"
                print(f"""Successfully created a {expense_type} with the following details:
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