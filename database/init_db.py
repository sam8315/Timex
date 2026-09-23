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


def migrate_employee_address_city_id(bind_engine=None) -> None:
    """
    Production-safe migration for the Phase 6 city_id normalization.

    Base.metadata.create_all() only creates missing tables — it does NOT add
    columns, indexes or FK constraints to tables that already exist. For an
    existing employee_addresses table this ensures (idempotently):
      - city_id column exists (nullable, existing rows untouched)
      - index on employee_addresses.city_id exists
      - FK employee_addresses.city_id -> cities.id with ON DELETE RESTRICT
    Safe to run repeatedly; never modifies existing city_id data.
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "employee_addresses" not in inspector.get_table_names():
        return

    with target.connect() as conn:
        columns = {row["name"] for row in inspector.get_columns("employee_addresses")}
        if "city_id" not in columns:
            conn.execute(text('ALTER TABLE "employee_addresses" ADD COLUMN "city_id" INTEGER NULL'))
            conn.commit()
            print("  + column employee_addresses.city_id added")

        index_names = {idx["name"] for idx in inspector.get_indexes("employee_addresses")}
        if "ix_employee_addresses_city_id" not in index_names:
            conn.execute(text(
                'CREATE INDEX "ix_employee_addresses_city_id" '
                'ON "employee_addresses" ("city_id")'
            ))
            conn.commit()
            print("  + index ix_employee_addresses_city_id added")

        has_fk = any(
            fk.get("referred_table") == "cities"
            and fk.get("referred_columns") == ["id"]
            and "city_id" in (fk.get("constrained_columns") or [])
            for fk in inspector.get_foreign_keys("employee_addresses")
        )
        if not has_fk:
            conn.execute(text(
                'ALTER TABLE "employee_addresses" '
                'ADD CONSTRAINT "employee_addresses_city_id_fkey" '
                'FOREIGN KEY ("city_id") REFERENCES "cities" ("id") ON DELETE RESTRICT'
            ))
            conn.commit()
            print("  + fk employee_addresses.city_id -> cities.id added")


def migrate_employee_address_coords_pair(bind_engine=None) -> None:
    """
    Enforce complete coordinate pairs on existing employee_addresses tables.

    - Detects rows with exactly one of latitude/longitude set. Such rows
      are NOT auto-fixed (the missing coordinate must not be invented):
      the migration fails with a clear error so the data can be cleaned
      up manually first.
    - Otherwise adds the ck_employee_address_coords_pair CHECK if missing.
    Idempotent; never modifies address data.
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "employee_addresses" not in inspector.get_table_names():
        return

    with target.connect() as conn:
        partial = conn.execute(text(
            "SELECT COUNT(*) FROM employee_addresses "
            "WHERE (latitude IS NULL AND longitude IS NOT NULL) "
            "OR (latitude IS NOT NULL AND longitude IS NULL)"
        )).scalar_one()
        if partial:
            raise RuntimeError(
                f"employee_addresses has {partial} row(s) with only one "
                "of latitude/longitude set. Clean them up manually "
                "(set both NULL or both valid) before this migration can "
                "add the ck_employee_address_coords_pair CHECK constraint."
            )
        # Scope by table OID: a same-named constraint on another table
        # must not satisfy this check.
        exists = conn.execute(text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_employee_address_coords_pair' "
            "AND conrelid = 'employee_addresses'::regclass"
        )).scalar()
        if not exists:
            conn.execute(text(
                'ALTER TABLE "employee_addresses" '
                'ADD CONSTRAINT "ck_employee_address_coords_pair" '
                'CHECK ((latitude IS NULL AND longitude IS NULL) OR '
                '(latitude IS NOT NULL AND longitude IS NOT NULL))'
            ))
            conn.commit()
            print("  + check ck_employee_address_coords_pair added")


def migrate_employee_address_nan_check(bind_engine=None) -> None:
    """
    Reject NaN in latitude/longitude via CHECK constraints.

    - Detects rows containing NaN in either coordinate.
      Such rows block the migration (no data is modified).
    - Adds the CHECK only when existing data is safe.
    - Idempotent; repeated execution is safe (skips existing constraints).
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "employee_addresses" not in inspector.get_table_names():
        return

    with target.connect() as conn:
        nan_count = conn.execute(text(
            "SELECT COUNT(*) FROM employee_addresses "
            "WHERE latitude = 'NaN' OR longitude = 'NaN'"
        )).scalar_one()
        if nan_count:
            raise RuntimeError(
                f"employee_addresses has {nan_count} row(s) with NaN "
                "coordinates. Clean them up manually before this "
                "migration can add the NaN CHECK constraints."
            )

        for column, constraint_name in [
            ("latitude", "ck_employee_address_latitude_not_nan"),
            ("longitude", "ck_employee_address_longitude_not_nan"),
        ]:
            exists = conn.execute(text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = :name "
                "AND conrelid = 'employee_addresses'::regclass"
            ), {"name": constraint_name}).scalar()
            if not exists:
                conn.execute(text(
                    f'ALTER TABLE "employee_addresses" '
                    f'ADD CONSTRAINT "{constraint_name}" '
                    f"CHECK ({column} IS NULL OR {column} <> 'NaN'::numeric)"
                ))
                conn.commit()
                print(f"  + check {constraint_name} added")


def migrate_employee_address_range_check(bind_engine=None) -> None:
    """
    Enforce coordinate range constraints on existing employee_addresses.

    - Detects rows with out-of-range latitude (-90..90) or
      longitude (-180..180). Such rows block the migration
      (no data is modified).
    - Adds the CHECK only when existing data is safe.
    - Idempotent; repeated execution skips existing constraints.
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "employee_addresses" not in inspector.get_table_names():
        return

    with target.connect() as conn:
        out_of_range = conn.execute(text(
            "SELECT COUNT(*) FROM employee_addresses "
            "WHERE (latitude IS NOT NULL AND "
            "(latitude < -90 OR latitude > 90)) "
            "OR (longitude IS NOT NULL AND "
            "(longitude < -180 OR longitude > 180))"
        )).scalar_one()
        if out_of_range:
            raise RuntimeError(
                f"employee_addresses has {out_of_range} row(s) with "
                "out-of-range coordinates. Clean them up manually "
                "(set values within -90..90 for latitude and "
                "-180..180 for longitude) before this migration "
                "can add the range CHECK constraints."
            )

        for column, constraint_name, low, high in [
            ("latitude", "ck_employee_address_latitude_range", -90, 90),
            ("longitude", "ck_employee_address_longitude_range", -180, 180),
        ]:
            exists = conn.execute(text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = :name "
                "AND conrelid = 'employee_addresses'::regclass"
            ), {"name": constraint_name}).scalar()
            if not exists:
                conn.execute(text(
                    f'ALTER TABLE "employee_addresses" '
                    f'ADD CONSTRAINT "{constraint_name}" '
                    f'CHECK ({column} IS NULL OR '
                    f'({column} >= {low} AND {column} <= {high}))'
                ))
                conn.commit()
                print(f"  + check {constraint_name} added")


def migrate_employee_address_history(bind_engine=None) -> None:
    """
    Audit tables must survive deletions: employee_address_history keeps no
    FK on address_id or user_id. Tables created before the FK removal still
    carry employee_address_history.user_id -> users.user_id — drop that
    constraint when present. Idempotent; never touches history data.
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "employee_address_history" not in inspector.get_table_names():
        return

    stale = [
        fk.get("name") for fk in inspector.get_foreign_keys(
            "employee_address_history")
        if "user_id" in (fk.get("constrained_columns") or [])
    ]
    if not stale:
        return
    with target.connect() as conn:
        for name in stale:
            if name:
                conn.execute(text(
                    f'ALTER TABLE "employee_address_history" '
                    f'DROP CONSTRAINT "{name}"'
                ))
        conn.commit()
        print(f"  - fk dropped from employee_address_history.user_id: {stale}")


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
    """Seed contract-scoped Travel Leave policies, rules, and default quotas."""
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

            # Seed one default annual quota per marital status when missing.
            for marital_status in ("S", "M"):
                quota_exists = conn.execute(
                    _sql_text(
                        """
                        SELECT 1
                        FROM travel_leave_quota_settings
                        WHERE policy_id = :policy_id
                          AND marital_status = :marital_status
                        LIMIT 1
                        """
                    ),
                    {
                        "policy_id": policy_id,
                        "marital_status": marital_status,
                    },
                ).scalar()

                if quota_exists is None:
                    conn.execute(
                        _sql_text(
                            """
                            INSERT INTO travel_leave_quota_settings
                                (policy_id, marital_status, annual_max_usage,
                                 description, parameter_key, parameter_value)
                            VALUES
                                (:policy_id, :marital_status, 3,
                                 'Max approved travel leave uses per Jalali year',
                                 :parameter_key, '3')
                            """
                        ),
                        {
                            "policy_id": policy_id,
                            "marital_status": marital_status,
                            "parameter_key": f"annual_max_usage_{contract_type_code}_{marital_status}",
                        },
                    )

        print("  + contract-scoped travel_leave policies/rules/quotas seeded")


# Canonical active Iranian bank reference set (Phase 12).
# Ordered for deterministic sort_order. Codes are 3-char strings (leading zeros).
# Excluded intentionally: merged/revoked banks, central bank, foreign banks,
# non-bank credit institutions (Ansar, Ghavamin, Hekmat, Mehr Eghtesad, etc.).
CANONICAL_BANKS = (
    ("011", "بانک صنعت و معدن"),
    ("012", "بانک ملت"),
    ("013", "بانک رفاه کارگران"),
    ("014", "بانک مسکن"),
    ("015", "بانک سپه"),
    ("016", "بانک کشاورزی"),
    ("017", "بانک ملی ایران"),
    ("018", "بانک تجارت"),
    ("019", "بانک صادرات ایران"),
    ("020", "بانک توسعه صادرات ایران"),
    ("021", "پست بانک ایران"),
    ("022", "بانک توسعه تعاون"),
    ("053", "بانک کارآفرین"),
    ("054", "بانک پارسیان"),
    ("055", "بانک اقتصاد نوین"),
    ("056", "بانک سامان"),
    ("057", "بانک پاسارگاد"),
    ("058", "بانک سرمایه"),
    ("059", "بانک سینا"),
    ("060", "بانک قرض‌الحسنه مهر ایران"),
    ("061", "بانک شهر"),
    ("064", "بانک گردشگری"),
    ("066", "بانک دی"),
    ("069", "بانک ایران‌زمین"),
    ("070", "بانک قرض‌الحسنه رسالت"),
    ("078", "بانک خاورمیانه"),
    ("095", "بانک مشترک ایران و ونزوئلا"),
)


def seed_banks(bind_engine=None) -> None:
    """
    Synchronize the canonical Iranian bank reference set (idempotent upsert).

    - Existing canonical code → update Persian name, country_code='IR',
      is_active=true, sort_order from the canonical list order.
    - Missing canonical bank → insert.
    - Existing code NOT in the canonical active set → set is_active=false
      (never delete: employee_bank_accounts.bank_id is a restrictive FK).
    """
    from sqlalchemy import text as _sql_text

    target = bind_engine if bind_engine is not None else engine
    canonical_codes = {code for code, _ in CANONICAL_BANKS}

    with target.begin() as conn:
        for sort_order, (code, name) in enumerate(CANONICAL_BANKS, start=1):
            conn.execute(
                _sql_text(
                    """
                    INSERT INTO banks (code, name, country_code, is_active, sort_order)
                    VALUES (:code, :name, 'IR', TRUE, :sort_order)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        country_code = EXCLUDED.country_code,
                        is_active = EXCLUDED.is_active,
                        sort_order = EXCLUDED.sort_order
                    """
                ),
                {"code": code, "name": name, "sort_order": sort_order},
            )

        existing_codes = [
            row[0] for row in conn.execute(_sql_text("SELECT code FROM banks"))
        ]
        for code in existing_codes:
            if code not in canonical_codes:
                conn.execute(
                    _sql_text(
                        "UPDATE banks SET is_active = FALSE WHERE code = :code"
                    ),
                    {"code": code},
                )
        print(f"  + Iranian banks synchronized ({len(CANONICAL_BANKS)} active)")


def create_tables() -> None:
    """
    ساخت تمام جداول تعریف شده در مدل‌ها
    اگر جدول از قبل وجود داشته باشد، تغییری ایجاد نمی‌کند
    """
    try:
        migrate_missing_columns()
        Base.metadata.create_all(bind=engine)
        migrate_employee_address_city_id()
        migrate_employee_address_history()
        migrate_employee_address_coords_pair()
        migrate_employee_address_nan_check()
        migrate_employee_address_range_check()
        migrate_time_columns()
        migrate_data_fixes()
        seed_travel_leave_policy_rules()
        seed_banks()
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
