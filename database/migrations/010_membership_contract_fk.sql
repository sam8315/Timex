-- Add FK contracts.contract_type_code → membership_types.code
-- Run only after seed + orphan check (see migrate_membership_contract_fk in init_db.py).
-- This file documents the intended SQL; runtime path is fail-closed in Python.

-- Abort manually if orphans exist:
-- SELECT id, contract_type_code FROM contracts c
-- WHERE NOT EXISTS (SELECT 1 FROM membership_types m WHERE m.code = c.contract_type_code);

ALTER TABLE contracts
    ADD CONSTRAINT fk_contracts_membership_type_code
    FOREIGN KEY (contract_type_code)
    REFERENCES membership_types(code)
    ON DELETE RESTRICT;
