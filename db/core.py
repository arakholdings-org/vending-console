from tinydb import TinyDB, Query


db = TinyDB("db.json")
query = Query()

Sales = db.table("sales")
Prices = db.table("prices")
