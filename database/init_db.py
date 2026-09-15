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


def seed_travel_leave_policy_rules() -> None:
    """Seed contract-scoped Travel Leave policies and their default rules."""
    from sqlalchemy import text as _sql_text

    contract_types = ("1", "2", "3", "4", "5", "6", "7")

    with engine.begin() as conn:
        for contract_type_code in contract_types:
            # Ensure one policy exists for each contract type.
            policy_result = conn.execute(
                _sql_text(
                    """
                    INSERT INTO travel_leave_policies
                        (contract_type_code, is_enabled, distance_method, description)
                    VALUES
                        (:code, TRUE, 'geographic', 'Default Travel Leave policy')
                    ON CONFLICT (contract_type_code) DO NOTHING
                    RETURNING id
                    """
                ),
                {"code": contract_type_code},
            )
            policy_row = policy_result.fetchone()

            if policy_row is not None:
                policy_id = policy_row[0]
            else:
                policy_id = conn.execute(
                    _sql_text(
                        """
                        SELECT id
                        FROM travel_leave_policies
                        WHERE contract_type_code = :code
                        """
                    ),
                    {"code": contract_type_code},
                ).scalar_one()

            # Seed rules only when this policy has no rules.
            rule_count = conn.execute(
                _sql_text(
                    """
                    SELECT COUNT(*)
                    FROM travel_leave_policy_rules
                    WHERE policy_id = :policy_id
                    """
                ),
                {"policy_id": policy_id},
            ).scalar_one()

            if rule_count == 0:
                conn.execute(
                    _sql_text(
                        """
                        INSERT INTO travel_leave_policy_rules
                            (policy_id, min_km, max_km, travel_days, description, is_active)
                        VALUES
                            (:policy_id, 0.0, 199.99, 0,
                             'Below 200 km — ineligible', 1),
                            (:policy_id, 200.0, 500.0, 1,
                             '200–500 km — 1 travel day', 1),
                            (:policy_id, 500.01, 1500.0, 2,
                             '501–1500 km — 2 travel days', 1),
                            (:policy_id, 1500.01, 99999.0, 3,
                             'Above 1500 km — 3 travel days', 1)
                        """
                    ),
                    {"policy_id": policy_id},
                )

        print("  + contract-scoped travel_leave policies/rules seeded")

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
        seed_travel_leave_policy_rules()
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
