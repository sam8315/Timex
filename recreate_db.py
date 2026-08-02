# from database.init_db import create_tables
# create_tables()
# print("✅ جداول با ساختار جدید ساخته شدند.")



from database.init_db import create_tables, check_tables

print("🔧 در حال ساخت جداول جدید...")
create_tables()
check_tables()
print("✅ تست کامل شد")