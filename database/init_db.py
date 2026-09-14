"""
مدیریت ساخت و مقداردهی اولیه جداول دیتابیس
"""
from sqlalchemy import inspect, text, types as sa_types
from database.engine import engine
from models import Base


def _column_ddl(column) -> str:
    """Convert a SQLAlchemy column definition to a PostgreSQL DDL type string."""
    col_type = column.type
    if isinstance(col_type, sa_types.Integer):
        dtype = "INTEGER"
    elif isinstance(col_type, sa_types.BigInteger):
        dtype = "BIGINT"
    elif isinstance(col_type, sa_types.Boolean):
        dtype = "BOOLEAN"
    elif isinstance(col_type, sa_types.Float):
        dtype = "FLOAT"
    elif isinstance(col_type, sa_types.String):
        length = col_type.length or 255
        dtype = f"VARCHAR({length})"
    elif isinstance(col_type, sa_types.Text):
        dtype = "TEXT"
    elif isinstance(col_type, sa_types.DateTime):
        dtype = "TIMESTAMP WITH TIME ZONE"
    elif isinstance(col_type, sa_types.Date):
        dtype = "DATE"
    elif isinstance(col_type, sa_types.Time):
        dtype = "TIME"
    elif isinstance(col_type, sa_types.Numeric):
        dtype = "NUMERIC"
    else:
        dtype = "TEXT"

    # Add new columns as NULL to avoid integrity errors on existing rows.
    return f"{dtype} NULL"


def migrate_missing_columns() -> None:
    """
    مقایسه ستون‌های مدل‌ها با جداول موجود در دیتابیس
    و اضافه کردن ستون‌های جدید بدون آسیب به داده‌های قبلی.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table_name, table_obj in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        db_columns = {row["name"] for row in inspector.get_columns(table_name)}
        for column in table_obj.columns:
            if column.name not in db_columns:
                ddl = _column_ddl(column)
                with engine.connect() as conn:
                    conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {ddl}'))
                    conn.commit()
                print(f"  + column {table_name}.{column.name} added")


def migrate_time_columns() -> None:
    """
    Ensure LeaveRequest hourly time columns match the SQLAlchemy TIME type.

    Older databases may have received start_time/end_time while _column_ddl()
    did not know about sa_types.Time, causing those columns to be created as TEXT.
    PostgreSQL then returns strings from those columns instead of datetime.time.
    Convert existing textual HH:MM values to TIME and leave NULL/empty values NULL.
    """
    inspector = inspect(engine)
    if "leave_requests" not in inspector.get_table_names():
        return

    columns = {row["name"]: row for row in inspector.get_columns("leave_requests")}
    for column_name in ("start_time", "end_time"):
        column = columns.get(column_name)
        if not column or isinstance(column["type"], sa_types.Time):
            continue

        with engine.connect() as conn:
            conn.execute(text(
                f'ALTER TABLE "leave_requests" '
                f'ALTER COLUMN "{column_name}" TYPE TIME '
                f'USING CASE '
                f'WHEN "{column_name}" IS NULL OR BTRIM(CAST("{column_name}" AS TEXT)) = \'\' '
                f'THEN NULL '
                f'ELSE CAST("{column_name}" AS TIME) END'
            ))
            conn.commit()
        print(f"  ~ column leave_requests.{column_name} converted to TIME")


def migrate_data_fixes(bind_engine=None) -> None:
    """
    پاک‌سازی داده‌های قدیمی بدون آسیب به رکوردها.
    - حذف فاصله‌های اضافی کد وضعیت روزانه (مثل 'R ' که باعث خالی
      ماندن ستون وضعیت و نمایش داده نشدن در گزارش می‌شد).
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "daily_statuses" not in inspector.get_table_names():
        return
    with target.connect() as conn:
        result = conn.execute(text(
            "UPDATE daily_statuses SET status_code = TRIM(status_code) "
            "WHERE status_code <> TRIM(status_code)"
        ))
        conn.commit()
        if result.rowcount:
            print(f"  + trimmed status_code on {result.rowcount} daily_statuses row(s)")


def create_tables() -> None:
    """
    ساخت تمام جداول تعریف شده در مدل‌ها
    اگر جدول از قبل وجود داشته باشد، تغییری ایجاد نمی‌کند
    """
    try:
        migrate_missing_columns()
        Base.metadata.create_all(bind=engine)
        migrate_time_columns()
        migrate_data_fixes()
        print("✅ جداول دیتابیس با موفقیت ساخته/بررسی شدند")
    except Exception as e:
        print(f"❌ خطا در ساخت جداول: {e}")
        raise


def check_tables() -> None:
    """بررسی و نمایش جداول موجود در دیتابیس"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if not tables:
        print("⚠️  هیچ جدولی در دیتابیس وجود ندارد")
        return

    print(f"\n📊 جداول دیتابیس موجود ({len(tables)} جدول):")
    for table in tables:
        columns = inspector.get_columns(table)
        print(f"  • {table} ({len(columns)} ستون)")


def drop_all_tables() -> None:
    """
    حذف تمام جداول (فقط برای توسعه - با احتیاط استفاده شود!)
    """
    try:
        Base.metadata.drop_all(bind=engine)
        print("⚠️  تمام جداول حذف شدند")
    except Exception as e:
        print(f"❌ خطا در حذف جداول: {e}")
        raise


if __name__ == "__main__":
    # اجرای مستقیم برای تست
    print("🔧 در حال ساخت جداول...")
    create_tables()
    check_tables()

# Travel Leave bootstrap (idempotent)
from sqlalchemy import text
from database.engine import engine

def bootstrap_travel_leave_policy():
    with engine.begin() as conn:
        r = conn.execute(text("SELECT id FROM policies WHERE category='travel_leave' AND name='Travel Leave Policy' LIMIT 1"))
        row = r.fetchone()
        if not row:
            conn.execute(text("INSERT INTO policies (category,name,description,is_active,effective_from_year) VALUES ('travel_leave','Travel Leave Policy','Default travel leave policy',true,1405)"))
            pid = conn.execute(text("SELECT id FROM policies WHERE category='travel_leave' AND name='Travel Leave Policy' LIMIT 1")).scalar()
            for k,v in [('annual_max_usage','3'),('rule_200_500','1'),('rule_501_1500','2'),('rule_1501_plus','3')]:
                conn.execute(text('INSERT INTO policy_values (policy_id,parameter_key,parameter_value,is_editable,notes) VALUES (:pid,:k,:v,true,:note)'), {'pid':pid,'k':k,'v':v,'note':'default'})
            print('Travel Leave bootstrap complete (policy created)')
        else:
            print('Travel Leave bootstrap skipped (already exists)')

bootstrap_travel_leave_policy()
