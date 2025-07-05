from tinydb import TinyDB, Query


db = TinyDB("db.json")
query = Query()

Inventory = db.table("inventory")
Prices = db.table("prices")
