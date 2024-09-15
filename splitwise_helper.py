from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.expense import ExpenseUser


# def __init__(self, sw):
#     self.consumer_key = consumer_key
#     self.consumer_secret = consumer_secret
#     self.api_key = api_key
    
#     # print(f"consumer_key {consumer_key}, consumer_secret {consumer_secret}, api_key {api_key}")
#     self.sw = sw

def get_friends(sw):
    return sw.getFriends()

def print_friends(sw):
    friends = sw.getFriends()
    for friend in friends:
        print(friend.first_name)

def get_groups(sw):
    return sw.getGroups()

def print_groups(sw):
    groups = sw.getGroups()
    for group in groups:
        print(group.name)

def get_expenses(sw, group_id):
    return sw.getExpenses(group_id=group_id)

def print_expenses(sw, expenses):
    for expense in expenses:
        print(expense)
        print('')

def get_currencies(sw):
    return sw.getCurrencies()

def get_categories(sw):
    return sw.getCategories()

def print_categories(categories):
    for category in categories:
        print(category)
        
def format_user(name, userId, paid_share, owed_share):
    return {"name": name, "userId": userId, "paid-share": paid_share, "owed-share": owed_share}

#Creates and publishes an expense
def create_expense(sw, description, cost, groupid, users):
    '''
    users =  [{"name": "Alex",
                "userId": 28199,
                "paid-share": 100,
                "owed-share": 20.0
                },
                ...]
    '''    
    #Set overall expense data
    expense = Expense()
    expense.setGroupId(groupid)
    expense.setCost(str(cost))
    expense.setDescription(description)
    
    # set user expenses
    for user in users:
        u = ExpenseUser()
        u.setId(user["userId"])
        u.setPaidShare(str(user["paid-share"]))
        u.setOwedShare(str(user["owed-share"]))
        expense.addUser(u)
    nExpense, errors = sw.createExpense(expense)
    # print(errors.errors['base'])
    print(nExpense.getId())



'''
Consumer Key
I6ywnLX27pPHttGhOsxTfVXccpGkTs42sKGQkXVM

Consumer Secret
UPxWHRp4vppr6ZbCyjzknfkaxHxgVIkohuT4O6AB

API keys
AC7gO1NLKpHxBziHbTdUWcnkzcRdn5gYyuGrS2GU

OAuth 1.0

Request Token URL
https://secure.splitwise.com/oauth/request_token

Access Token URL
https://secure.splitwise.com/oauth/access_token

Authorize URL
https://secure.splitwise.com/oauth/authorize


OAuth 2.0

Token URL
https://secure.splitwise.com/oauth/token

Authorize URL
https://secure.splitwise.com/oauth/authorize


'''