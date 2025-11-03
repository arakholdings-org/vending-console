from tinydb import TinyDB, Query


db = TinyDB("db.json")
sales_db = TinyDB("sales.json")
transactions_db = TinyDB("transactions.json")


query = Query()
Sales = sales_db.table("sales")
Prices = db.table("prices")
Transaction = transactions_db.table("transactions")
