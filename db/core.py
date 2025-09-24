from tinydb import TinyDB, Query


db = TinyDB("db.json")
sales_db = TinyDB("sales.json")
jams_db = TinyDB("jams.json")
transactions_db = TinyDB("transactions.json")
stocks_db = TinyDB("stock.json")

query = Query()

Sales = sales_db.table("sales")
Prices = db.table("prices")
Jams = jams_db.table("jams")
Transaction = transactions_db.table("transactions")
Stock = stocks_db.table("stock")
