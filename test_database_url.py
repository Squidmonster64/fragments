import os

os.environ["DATABASE_URL"] = "mysql://owner:secret@mysql.railway.internal:3306/railway"

from app.database import DATABASE_URL, engine

assert DATABASE_URL.startswith("mysql+pymysql://"), DATABASE_URL
assert engine.url.get_backend_name() == "mysql"
print("managed database URL check passed")
