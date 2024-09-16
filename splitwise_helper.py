from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.expense import ExpenseUser


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

# Creates and publishes an expense.  Returns expenseId
def create_expense(sw, description, cost, groupId, users, retries=3):
    while retries > 0:
        retries -= 1
        '''
        users =  [{"name": "Alex",
                    "userId": 28199,
                    "paid-share": 100,
                    "owed-share": 20.0
                    },
                    ...]
        ''' 
        if description:
            if cost:
                if groupId:
                    if users:
                        #Set overall expense data
                        expense = Expense()
                        expense.setGroupId(groupId)
                        expense.setCost(str(cost))
                        expense.setDescription(description)
                        
                        # set user expenses
                        for user in users:
                            u = ExpenseUser()
                            u.setId(user["userId"])
                            u.setPaidShare(str(user["paid-share"]))
                            u.setOwedShare(str(user["owed-share"]))
                            expense.addUser(u)
                    else:
                        print("Missing individual user expense details")
                else:
                    print("Missing groupID")
            else:
                print("Missing cost")
        else:
            print("Missing description")
    

        nExpense, errors = sw.createExpense(expense)
        if errors in locals():
            print(errors.errors['base'])
        else:
            return nExpense.getId()