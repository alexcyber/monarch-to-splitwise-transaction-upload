# monarch-to-splitwise-transaction-upload
A python script that takes a Monarch Money transaction and adds it to the appropriate splitwise group.  Uses monarch tags to control splitwise group selection as well as who owes what.

## Workflow
1. Transaction comes into Monarch Money and hits Monarch Money transaction rule
1. Monarch Money transaction rule splits and/or adds tags to transaction
    * The Monarch Money Transaction rule will have tag setting rules that specify which Splitwise group is associated with the expense and who is responsible for paying
1. This script runs and catalogs Monarch Money transactions that need to be uploaded to Splitwise.  
1. The script will process amount owed by each payee and upload to splitwise the transactions including group ID and payee ID
1. The script will then update Monarch Money tag information and repeat as necessary for all transactions

## Setup Guide
### Create config.yaml
1. Duplicate config_example.yaml and rename the duplicate to config.yaml.
    * Config.yamnl will be your template config file.  All values that need to be filled in are here for your convienence

### Add Credentials to config.yaml
1. Configure Splitwise credentials:
    * Get credentials from https://secure.splitwise.com/apps
    * Set sw_consumer_key
    * Set sw_consumer_secret  
    * Set sw_api_key
1. Configure Monarch credentials:
    * Set monarch_device_uuid
        * This is required due to recent changes to Monarch Money security posture.
        * The easiest way to get this information is through a browser.  For this guide, we will be using Firefox
            * Login to Monarch Money on the UI
            * Right click the page and select `Inspect`
            * You will see a new panel pop up within the firefox UI.  Within in, select `Console`
            * Type in `localStorage.getItem('monarchDeviceUUID')` and press `Enter`
                * Please note, copy and pasting may or may not work due to a security setting within Firefox.  Typing it in manually always works
            * Copy the returned into the `config.yaml` under `monarch_device_uuid`
    * Set monarch_user_email
    * Set monarch_user_password
1. Create and add key tag information:
    * Once Monarch credentials have been set, you run get_tag_info.py to get the created tags

### Create necessary tagging information for Monarch Money
In this section, you will be creating MonarchMoney tags that drives the logic of this script.  You will create 4 tag types, using different colors to differentiate the types.  Here is the breakdown of tag types
- **splitwise-group** = Specifies the color used by monarch tags that reference splitwise groups by name exactly. This color of tag is used to associate a specific transaction to a Splitwise Group
- **payee** = Specifies the color used by Monarch tags that identifies individual(s) who owe money.  The tag name must be exactly what the Splitwise Firstname of the individual
- **Not In Splitwise** = Specifies a transaction that should be in Splitwise but isn't yet.  In other words, marks the transactions that are ready to be inputed into Splitwise
- **In Splitwise** = Specifies a transaction that is in Splitwise already.  In other words, transactions that have already been processed  

Let's get started.

1. Navigate to https://app.monarchmoney.com/settings/tags in a browser
1. Select `New Tag` in the top right
1. Select the color selector field (the uni-colored circle)
1. Select a color to use for `splitwise-group` variable
    * Note: Whatever color you select, that color must only ever be used for denoting a splitwise group
1. Under "Name your tag...", enter the splitwise group you would like to associate with Monarch Money transactions
    * Note: This name must exactly match the group name in Splitwise
1. Select `Save`
1. (Optional) Create additional splitwise group tags as needed. All must use the same color; however, each one must be named differently (and match the group name is splitwise exactly)
1. Repeat the steps to create the `payee` tag.  This **must** be a different color from the other group types.  The name of each tag must correlate to Splitwise group members.  
    * For instance, if "Rachael" is a member of the splitwise group, you must name your tag "Rachael"
1. (Optional) Create additional payee group tags as needed.  All must use the same color; however, each one must be named differently.  Payee tags are reused amongst all groups.  You do not need to create multiple copies for each splitwise group.
    * Limitations:
        * All users first name must be unique to the group.  We will (potentially) add an enhancement to support multiple group members who share the same first name in the future 
1. Repeat the steps to create the 'Not In Splitwise` tag.  There should only be on tag created.  Like the other tag groups, it must be a different color with that color only ever being used for the tag group
1. Repeat the steps to create the 'In Splitwise` tag.  There should only be on tag created. 

### Get tag color codes for config.yaml
1. Make sure you have the monarch credentials added to config.yaml
1. Run `get_tags_info.py` to get color codes for each tag
1. Copy over the respective color codes to config.yaml `key_tag_colors` variable
    * Note: Do not change the keys of key_tag_colors.

### Create Monarch Money rules to autotag transactions
Now it's time to add the Monarch Money rules that allow auto-tag transactions in Monarch Money and sets them up to be added to Splitwise.  You will find that using Monarch Money rules allows for flexibility in how payments are split in Splitwise.  For instance, the following scenarios are possible
- Uneven splitting of transactions
- Hiding costs completely from Monarch Money for purchases of others
- Hiding partial costs for group expenses
- Documentation of all transactions and responsibility
1. https://app.monarchmoney.com/settings/rules
1. `create rule`
1. Add match criteria depending on use case
1. Option A: Split Transaction
    1. Splitting a tag allows you to add uneven cost pricing for payment
    * Add tags.  You **must** add at least one tag of each of the following groups: `splitwise-group`, `payee`, `Not In Splitwise` to the rule for it to trigger properly
1. Option B: Don't split transaction
    * Add tags.  You **must** add at least one tag of each of the following groups: `splitwise-group`, `payee`, `Not In Splitwise` to the rule for it to trigger properly


### (Optional) Added easy Splitwise descriptions:

