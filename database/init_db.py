"""
مدیریت ساخت و مقداردهی اولیه جداول دیتابیس
"""
import logging
from sqlalchemy import inspect, text, types as sa_types
from database.engine import engine
from models import Base

logger = logging.getLogger(__name__)


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
                logger.info(
                    "Column added table=%s column=%s",
                    table_name,
                    column.name,
                    extra={"event": "database.ready"},
                )


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
        logger.info(
            "Column converted to TIME table=leave_requests column=%s",
            column_name,
            extra={"event": "database.ready"},
        )


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
            logger.info(
                "Column added table=employee_addresses column=city_id",
                extra={"event": "database.ready"},
            )

        index_names = {idx["name"] for idx in inspector.get_indexes("employee_addresses")}
        if "ix_employee_addresses_city_id" not in index_names:
            conn.execute(text(
                'CREATE INDEX "ix_employee_addresses_city_id" '
                'ON "employee_addresses" ("city_id")'
            ))
            conn.commit()
            logger.info(
                "Index added name=ix_employee_addresses_city_id",
                extra={"event": "database.ready"},
            )

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
            logger.info(
                "Foreign key added employee_addresses.city_id -> cities.id",
                extra={"event": "database.ready"},
            )


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
            logger.info(
                "Check constraint added name=ck_employee_address_coords_pair",
                extra={"event": "database.ready"},
            )


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
                logger.info(
                    "Check constraint added name=%s",
                    constraint_name,
                    extra={"event": "database.ready"},
                )


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
                logger.info(
                    "Check constraint added name=%s",
                    constraint_name,
                    extra={"event": "database.ready"},
                )


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
        logger.info(
            "Foreign keys dropped from employee_address_history.user_id count=%s",
            len(stale),
            extra={"event": "database.ready"},
        )


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
            logger.info(
                "Trimmed status_code on daily_statuses rows=%s",
                result.rowcount,
                extra={"event": "database.ready"},
            )


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

        logger.info(
            "Travel leave policies/rules/quotas seeded",
            extra={"event": "database.ready"},
        )


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
        logger.info(
            "Iranian banks synchronized active_count=%s",
            len(CANONICAL_BANKS),
            extra={"event": "database.ready"},
        )


def migrate_employee_position_id(bind_engine=None) -> None:
    """
    Replace free-text employee.position with positions FK (no data migration).

    Idempotent steps:
      1. Ensure employee.position_id exists (nullable INTEGER)
      2. Ensure index on position_id
      3. Ensure FK employee.position_id -> positions.id ON DELETE SET NULL
      4. Drop legacy text column employee.position if present (values discarded)
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "employee" not in inspector.get_table_names():
        return
    if "positions" not in inspector.get_table_names():
        return

    with target.connect() as conn:
        columns = {row["name"] for row in inspector.get_columns("employee")}
        if "position_id" not in columns:
            conn.execute(text('ALTER TABLE "employee" ADD COLUMN "position_id" INTEGER NULL'))
            conn.commit()
            logger.info(
                "Column added table=employee column=position_id",
                extra={"event": "database.ready"},
            )

        # Refresh inspector state after possible ADD COLUMN
        inspector = inspect(target)
        index_names = {idx["name"] for idx in inspector.get_indexes("employee")}
        if "ix_employee_position_id" not in index_names:
            conn.execute(text(
                'CREATE INDEX "ix_employee_position_id" ON "employee" ("position_id")'
            ))
            conn.commit()
            logger.info(
                "Index added name=ix_employee_position_id",
                extra={"event": "database.ready"},
            )

        has_fk = any(
            fk.get("referred_table") == "positions"
            and fk.get("referred_columns") == ["id"]
            and "position_id" in (fk.get("constrained_columns") or [])
            for fk in inspector.get_foreign_keys("employee")
        )
        if not has_fk:
            conn.execute(text(
                'ALTER TABLE "employee" '
                'ADD CONSTRAINT "employee_position_id_fkey" '
                'FOREIGN KEY ("position_id") REFERENCES "positions" ("id") '
                'ON DELETE SET NULL'
            ))
            conn.commit()
            logger.info(
                "Foreign key added employee.position_id -> positions.id",
                extra={"event": "database.ready"},
            )

        columns = {row["name"] for row in inspector.get_columns("employee")}
        # Re-read after possible adds
        inspector = inspect(target)
        columns = {row["name"] for row in inspector.get_columns("employee")}
        if "position" in columns:
            # Drop any indexes that include only the legacy column first
            for idx in inspector.get_indexes("employee"):
                cols = idx.get("column_names") or []
                if cols == ["position"]:
                    idx_name = idx["name"]
                    conn.execute(text(f'DROP INDEX IF EXISTS "{idx_name}"'))
                    conn.commit()
                    logger.info(
                        "Index dropped name=%s",
                        idx_name,
                        extra={"event": "database.ready"},
                    )
            conn.execute(text('ALTER TABLE "employee" DROP COLUMN "position"'))
            conn.commit()
            logger.info(
                "Column dropped table=employee column=position (no data migrated)",
                extra={"event": "database.ready"},
            )


def migrate_city_region_code(bind_engine=None) -> None:
    """Ensure cities.region_code exists with DEFAULT NORMAL (idempotent)."""
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "cities" not in inspector.get_table_names():
        return
    columns = {row["name"] for row in inspector.get_columns("cities")}
    with target.connect() as conn:
        if "region_code" not in columns:
            conn.execute(text(
                'ALTER TABLE "cities" '
                "ADD COLUMN \"region_code\" VARCHAR(20) NOT NULL DEFAULT 'NORMAL'"
            ))
            conn.commit()
            logger.info(
                "Column added table=cities column=region_code",
                extra={"event": "database.ready"},
            )
        else:
            conn.execute(text(
                "UPDATE cities SET region_code = 'NORMAL' "
                "WHERE region_code IS NULL OR BTRIM(region_code) = ''"
            ))
            conn.commit()


def seed_service_health(bind_engine=None) -> None:
    """
    Ensure one current-state row exists for each Timex service (idempotent).

    Inserts web / adms / bale with unknown process/health when missing.
    Never updates existing rows (runtime monitoring owns those fields later).
    """
    from sqlalchemy import text as _sql_text

    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "service_health" not in inspector.get_table_names():
        return

    with target.begin() as conn:
        for service_name in ("web", "adms", "bale"):
            conn.execute(
                _sql_text(
                    """
                    INSERT INTO service_health (
                        service_name, process_state, health_state
                    )
                    VALUES (:service_name, 'unknown', 'unknown')
                    ON CONFLICT (service_name) DO NOTHING
                    """
                ),
                {"service_name": service_name},
            )
        logger.info(
            "Service health rows ensured count=3",
            extra={"event": "database.ready"},
        )


def seed_employee_document_types(bind_engine=None) -> None:
    """
    Ensure the eight legacy employee document types exist (idempotent).

    INSERT … ON CONFLICT (code) DO NOTHING — never overwrites admin edits
    to name / is_active / sort_order, and never deletes custom types.
    """
    from sqlalchemy import text as _sql_text
    from models.employee_document import LEGACY_DOCUMENT_TYPE_SEED

    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "employee_document_types" not in inspector.get_table_names():
        return

    with target.begin() as conn:
        for sort_order, (code, name) in enumerate(LEGACY_DOCUMENT_TYPE_SEED, start=1):
            conn.execute(
                _sql_text(
                    """
                    INSERT INTO employee_document_types (
                        code, name, is_active, sort_order
                    )
                    VALUES (:code, :name, TRUE, :sort_order)
                    ON CONFLICT (code) DO NOTHING
                    """
                ),
                {"code": code, "name": name, "sort_order": sort_order},
            )
    logger.info(
        "Employee document types seeded legacy_count=%s",
        len(LEGACY_DOCUMENT_TYPE_SEED),
        extra={"event": "database.ready"},
    )


def migrate_employee_document_types(bind_engine=None) -> None:
    """
    Migrate employee_documents.document_type (string) → document_type_id FK.

    Idempotent Production-safe steps:
      1. Require employee_document_types table
      2. Seed legacy types (ON CONFLICT DO NOTHING)
      3. If legacy document_type column exists:
         a. ADD document_type_id NULL + index if missing
         b. Backfill from document_type = type.code
         c. Fail hard if any row remains unmapped
         d. ADD FK ON DELETE RESTRICT if missing
         e. SET document_type_id NOT NULL
         f. DROP CHECK ck_employee_document_type if present
         g. DROP legacy document_type column (+ its indexes)
      4. If only document_type_id exists (fresh schema): ensure FK exists
    Never deletes employee_documents rows or storage files.
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    tables = set(inspector.get_table_names())
    if "employee_documents" not in tables:
        return
    if "employee_document_types" not in tables:
        return

    seed_employee_document_types(bind_engine=target)

    with target.connect() as conn:
        inspector = inspect(target)
        columns = {row["name"] for row in inspector.get_columns("employee_documents")}
        has_legacy = "document_type" in columns
        has_fk_col = "document_type_id" in columns

        if has_legacy and not has_fk_col:
            conn.execute(
                text(
                    'ALTER TABLE "employee_documents" '
                    'ADD COLUMN "document_type_id" INTEGER NULL'
                )
            )
            conn.commit()
            logger.info(
                "Column added table=employee_documents column=document_type_id",
                extra={"event": "database.ready"},
            )
            inspector = inspect(target)
            columns = {row["name"] for row in inspector.get_columns("employee_documents")}
            has_fk_col = "document_type_id" in columns

        if has_fk_col:
            inspector = inspect(target)
            index_names = {
                idx["name"] for idx in inspector.get_indexes("employee_documents")
            }
            if "ix_employee_documents_document_type_id" not in index_names:
                conn.execute(
                    text(
                        'CREATE INDEX "ix_employee_documents_document_type_id" '
                        'ON "employee_documents" ("document_type_id")'
                    )
                )
                conn.commit()
                logger.info(
                    "Index created name=ix_employee_documents_document_type_id",
                    extra={"event": "database.ready"},
                )

        if has_legacy and has_fk_col:
            conn.execute(
                text(
                    """
                    UPDATE employee_documents AS d
                    SET document_type_id = t.id
                    FROM employee_document_types AS t
                    WHERE d.document_type_id IS NULL
                      AND d.document_type = t.code
                    """
                )
            )
            conn.commit()

            unmapped = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM employee_documents
                    WHERE document_type_id IS NULL
                    """
                )
            ).scalar()
            if unmapped:
                samples = conn.execute(
                    text(
                        """
                        SELECT DISTINCT document_type
                        FROM employee_documents
                        WHERE document_type_id IS NULL
                        ORDER BY document_type
                        LIMIT 20
                        """
                    )
                ).fetchall()
                sample_codes = [row[0] for row in samples]
                raise RuntimeError(
                    "employee_documents migration aborted: "
                    f"{unmapped} row(s) have unmapped document_type values "
                    f"(samples={sample_codes}). "
                    "Fix or seed missing types before retrying."
                )

        # Ensure FK exists when document_type_id is present
        if has_fk_col:
            inspector = inspect(target)
            fk_names = {
                fk["name"]
                for fk in inspector.get_foreign_keys("employee_documents")
                if fk.get("name")
            }
            if "employee_documents_document_type_id_fkey" not in fk_names:
                # Only add FK when all non-null rows are valid (or column empty)
                bad_fk = conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM employee_documents d
                        WHERE d.document_type_id IS NOT NULL
                          AND NOT EXISTS (
                            SELECT 1 FROM employee_document_types t
                            WHERE t.id = d.document_type_id
                          )
                        """
                    )
                ).scalar()
                if bad_fk:
                    raise RuntimeError(
                        "employee_documents migration aborted: "
                        f"{bad_fk} row(s) have invalid document_type_id "
                        "before FK creation."
                    )
                conn.execute(
                    text(
                        'ALTER TABLE "employee_documents" '
                        'ADD CONSTRAINT "employee_documents_document_type_id_fkey" '
                        'FOREIGN KEY ("document_type_id") '
                        'REFERENCES "employee_document_types" ("id") '
                        "ON DELETE RESTRICT"
                    )
                )
                conn.commit()
                logger.info(
                    "Foreign key added employee_documents.document_type_id "
                    "-> employee_document_types.id",
                    extra={"event": "database.ready"},
                )

            # SET NOT NULL when safe
            null_count = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM employee_documents
                    WHERE document_type_id IS NULL
                    """
                )
            ).scalar()
            col_nullable = True
            for col in inspect(target).get_columns("employee_documents"):
                if col["name"] == "document_type_id":
                    col_nullable = bool(col.get("nullable", True))
                    break
            if null_count == 0 and col_nullable:
                conn.execute(
                    text(
                        'ALTER TABLE "employee_documents" '
                        'ALTER COLUMN "document_type_id" SET NOT NULL'
                    )
                )
                conn.commit()
                logger.info(
                    "Column employee_documents.document_type_id set NOT NULL",
                    extra={"event": "database.ready"},
                )

        if has_legacy:
            # Drop CHECK on legacy string column if present
            has_check = conn.execute(
                text(
                    """
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'ck_employee_document_type'
                      AND conrelid = 'employee_documents'::regclass
                    """
                )
            ).fetchone()
            if has_check:
                conn.execute(
                    text(
                        'ALTER TABLE "employee_documents" '
                        'DROP CONSTRAINT "ck_employee_document_type"'
                    )
                )
                conn.commit()
                logger.info(
                    "Constraint dropped name=ck_employee_document_type",
                    extra={"event": "database.ready"},
                )

            inspector = inspect(target)
            for idx in inspector.get_indexes("employee_documents"):
                cols = idx.get("column_names") or []
                if cols == ["document_type"]:
                    idx_name = idx["name"]
                    conn.execute(text(f'DROP INDEX IF EXISTS "{idx_name}"'))
                    conn.commit()
                    logger.info(
                        "Index dropped name=%s",
                        idx_name,
                        extra={"event": "database.ready"},
                    )

            inspector = inspect(target)
            columns = {
                row["name"] for row in inspector.get_columns("employee_documents")
            }
            if "document_type" in columns:
                # Safety: never drop until every row is mapped
                still_null = conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM employee_documents
                        WHERE document_type_id IS NULL
                        """
                    )
                ).scalar()
                if still_null:
                    raise RuntimeError(
                        "Refusing to drop employee_documents.document_type: "
                        f"{still_null} row(s) still have NULL document_type_id"
                    )
                conn.execute(
                    text('ALTER TABLE "employee_documents" DROP COLUMN "document_type"')
                )
                conn.commit()
                logger.info(
                    "Column dropped table=employee_documents column=document_type",
                    extra={"event": "database.ready"},
                )


def seed_membership_types(bind_engine=None) -> None:
    """
    Ensure the seven legacy membership types + first rules exist (idempotent).
    Never creates memberships beyond codes 1..7. Never rewrites contracts.
    """
    from sqlalchemy.orm import sessionmaker
    from web.services.membership_service import (
        lock_codes_with_history,
        seed_default_memberships,
    )

    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    tables = set(inspector.get_table_names())
    if "membership_types" not in tables or "membership_type_rules" not in tables:
        return

    SessionLocal = sessionmaker(bind=target, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        created = seed_default_memberships(db)
        locked = lock_codes_with_history(db)
        db.commit()
        logger.info(
            "Membership types seeded created=%s locked=%s",
            created,
            locked,
            extra={"event": "database.ready"},
        )
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to seed membership types",
            extra={"event": "database.operation_failed"},
        )
        raise
    finally:
        db.close()


def align_leave_policy_membership_67(bind_engine=None) -> None:
    """
    Ensure leave policy keys for memberships 6/7 exist with annual=0.
    Does not rewrite contracts or leave balances.
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "policies" not in inspector.get_table_names():
        return
    if "policy_values" not in inspector.get_table_names():
        return

    with target.begin() as conn:
        leave_id = conn.execute(
            text(
                "SELECT id FROM policies WHERE category = 'leave' "
                "ORDER BY id ASC LIMIT 1"
            )
        ).scalar()
        if leave_id is None:
            return
        for code in ("6", "7"):
            for key, value, notes in (
                (
                    f"annual_leave_dept_{code}",
                    "0",
                    f"هم‌ترازی cutover عضویت {code}",
                ),
                (
                    f"region_applies_dept_{code}",
                    "true",
                    f"اعمال منطقه برای عضویت {code}",
                ),
            ):
                exists = conn.execute(
                    text(
                        """
                        SELECT 1 FROM policy_values
                        WHERE policy_id = :pid
                          AND parameter_key = :key
                          AND region_code IS NULL
                        LIMIT 1
                        """
                    ),
                    {"pid": leave_id, "key": key},
                ).first()
                if exists:
                    # Only force annual_leave_dept_6/7 to 0 for cutover alignment
                    if key.startswith("annual_leave_dept_"):
                        conn.execute(
                            text(
                                """
                                UPDATE policy_values
                                SET parameter_value = :val
                                WHERE policy_id = :pid
                                  AND parameter_key = :key
                                  AND region_code IS NULL
                                """
                            ),
                            {"pid": leave_id, "key": key, "val": value},
                        )
                    continue
                conn.execute(
                    text(
                        """
                        INSERT INTO policy_values (
                            policy_id, parameter_key, parameter_value,
                            region_code, notes, created_at, updated_at
                        )
                        VALUES (
                            :pid, :key, :val, NULL, :notes, NOW(), NOW()
                        )
                        """
                    ),
                    {
                        "pid": leave_id,
                        "key": key,
                        "val": value,
                        "notes": notes,
                    },
                )
    logger.info(
        "Leave policy aligned for memberships 6/7",
        extra={"event": "database.ready"},
    )


def migrate_membership_contract_fk(bind_engine=None) -> None:
    """
    Add FK contracts.contract_type_code → membership_types.code after orphan check.
    Fail-closed: raises if unknown codes exist. Never remaps codes.
    """
    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    tables = set(inspector.get_table_names())
    if "contracts" not in tables or "membership_types" not in tables:
        return

    seed_membership_types(bind_engine=target)

    with target.connect() as conn:
        orphans = conn.execute(
            text(
                """
                SELECT id, contract_type_code
                FROM contracts c
                WHERE NOT EXISTS (
                    SELECT 1 FROM membership_types m
                    WHERE m.code = c.contract_type_code
                )
                ORDER BY id
                LIMIT 50
                """
            )
        ).fetchall()
        if orphans:
            detail = ", ".join(
                f"id={r[0]} code={r[1]!r}" for r in orphans
            )
            raise RuntimeError(
                "membership FK aborted: orphan contract_type_code values: "
                + detail
            )

        travel_orphans = []
        if "travel_leave_policies" in tables:
            travel_orphans = conn.execute(
                text(
                    """
                    SELECT id, contract_type_code
                    FROM travel_leave_policies p
                    WHERE NOT EXISTS (
                        SELECT 1 FROM membership_types m
                        WHERE m.code = p.contract_type_code
                    )
                    ORDER BY id
                    LIMIT 50
                    """
                )
            ).fetchall()
        if travel_orphans:
            detail = ", ".join(
                f"id={r[0]} code={r[1]!r}" for r in travel_orphans
            )
            raise RuntimeError(
                "membership FK aborted: orphan travel_leave_policies codes: "
                + detail
            )

        fks = {
            fk["name"]
            for fk in inspector.get_foreign_keys("contracts")
        }
        if "fk_contracts_membership_type_code" not in fks:
            conn.execute(
                text(
                    """
                    ALTER TABLE contracts
                    ADD CONSTRAINT fk_contracts_membership_type_code
                    FOREIGN KEY (contract_type_code)
                    REFERENCES membership_types(code)
                    ON DELETE RESTRICT
                    """
                )
            )
            conn.commit()
            logger.info(
                "FK added contracts.contract_type_code -> membership_types.code",
                extra={"event": "database.ready"},
            )


def seed_role_permissions(bind_engine=None) -> None:
    """
    Seed missing role_permissions rows from ALL_PERMISSIONS catalog (idempotent).

    Never overwrites existing rows — UI edits must persist across restarts.
    New permission codes added in code get inserted with catalog defaults.
    """
    from sqlalchemy import text as _sql_text
    from web.permissions import ALL_PERMISSIONS, KNOWN_ROLES, catalog_role_default

    target = bind_engine if bind_engine is not None else engine
    inspector = inspect(target)
    if "role_permissions" not in inspector.get_table_names():
        return

    inserted = 0
    with target.begin() as conn:
        for permission in ALL_PERMISSIONS:
            for role in KNOWN_ROLES:
                granted = catalog_role_default(permission, role)
                result = conn.execute(
                    _sql_text(
                        """
                        INSERT INTO role_permissions (
                            role, permission, granted, created_at, updated_at
                        )
                        VALUES (
                            :role, :permission, :granted, NOW(), NOW()
                        )
                        ON CONFLICT (role, permission) DO NOTHING
                        """
                    ),
                    {
                        "role": role,
                        "permission": permission,
                        "granted": granted,
                    },
                )
                try:
                    inserted += result.rowcount or 0
                except Exception:
                    pass
    logger.info(
        "Role permissions seeded inserted=%s",
        inserted,
        extra={"event": "database.ready"},
    )


def create_tables() -> None:
    """
    ساخت تمام جداول تعریف شده در مدل‌ها
    و افزودن ستون‌های جدید به جداول موجود بدون حذف داده.
    """
    try:
        # اول جداول جدید، بعد ستون‌های جدید روی جداول موجود
        Base.metadata.create_all(bind=engine)
        migrate_missing_columns()
        migrate_city_region_code()
        migrate_employee_position_id()
        migrate_employee_address_city_id()
        migrate_employee_address_history()
        migrate_employee_address_coords_pair()
        migrate_employee_address_nan_check()
        migrate_employee_address_range_check()
        migrate_time_columns()
        migrate_data_fixes()
        seed_travel_leave_policy_rules()
        seed_banks()
        seed_service_health()
        migrate_employee_document_types()
        seed_membership_types()
        align_leave_policy_membership_67()
        migrate_membership_contract_fk()
        seed_role_permissions()
        logger.info(
            "Database tables created/verified successfully",
            extra={"event": "database.ready"},
        )
    except Exception:
        logger.exception(
            "Failed to create/verify database tables",
            extra={"event": "database.operation_failed"},
        )
        raise


def check_tables() -> None:
    """بررسی و نمایش جداول موجود در دیتابیس"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if not tables:
        logger.warning(
            "No tables found in database",
            extra={"event": "database.ready"},
        )
        return

    logger.info(
        "Database tables present count=%s",
        len(tables),
        extra={"event": "database.ready"},
    )
    for table in tables:
        columns = inspector.get_columns(table)
        logger.info(
            "Table present name=%s columns=%s",
            table,
            len(columns),
            extra={"event": "database.ready"},
        )


def drop_all_tables() -> None:
    """
    حذف تمام جداول (فقط برای توسعه - با احتیاط استفاده شود!)
    """
    try:
        Base.metadata.drop_all(bind=engine)
        logger.warning(
            "All database tables dropped",
            extra={"event": "database.ready"},
        )
    except Exception:
        logger.exception(
            "Failed to drop database tables",
            extra={"event": "database.operation_failed"},
        )
        raise


if __name__ == "__main__":
    # اجرای مستقیم برای تست
    logger.info(
        "Building database tables",
        extra={"event": "database.ready"},
    )
    create_tables()
    check_tables()
