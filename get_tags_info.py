import asyncio
import yaml
from monarchmoney import MonarchMoney
import monarch_helper as mhelper


async def fetch_tags():
    """Fetch and print Monarch Money tag information."""
    # Load configuration
    # amazonq-ignore-next-line
    with open("config.yaml", "r") as file:
        config = yaml.safe_load(file)

    # Initialize MonarchMoney instance
    mm = MonarchMoney()
    mm._headers["Device-UUID"] = config["monarch_device_uuid"]
    credentials = {
        "username": config["monarch_user_email"],
        "password": config["monarch_user_password"],
    }

    # Login to MonarchMoney
    uuid = config["monarch_device_uuid"]
    mm = await mhelper.login(mm, credentials, uuid)

    # Fetch tags
    tags = await mm.get_transaction_tags()

    # Print tag information
    print("Monarch Money Tags:")
    for tag in tags["householdTransactionTags"]:
        print(f"Name: {tag['name']}\n\tColor: {tag['color']}\n\tID: {tag['id']}")

if __name__ == "__main__":
    asyncio.run(fetch_tags())