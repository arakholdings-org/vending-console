from tinydb import TinyDB, Query


db = TinyDB("db.json")
sales_db = TinyDB("sales.json")
query = Query()

Sales = sales_db.table("sales")
Prices = db.table("prices")
