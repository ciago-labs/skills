#!/usr/bin/env python3
"""Statement-order-aware and transaction-state-machine PostgreSQL DDL migration safety analyzer."""
import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope, redact_secrets, split_sql_statements


def _is_nonzero_timeout(val_str: str) -> bool:
    cleaned = val_str.strip().strip("'\"").lower()
    if cleaned in ("0", "0ms", "0s", "default", "false", "off", ""):
        return False
    return True


def analyze_migration_sql(sql_text: str, pg_version: int = 16) -> Dict[str, Any]:
    safe_sql = redact_secrets(sql_text)
    statements = split_sql_statements(safe_sql)
    findings: List[Dict[str, Any]] = []
    warnings: List[str] = []
    recommendations: List[str] = []

    # Sequential execution state machine
    in_transaction = False
    tx_depth = 0
    transactions_opened = 0
    transactions_committed = 0
    transactions_rolled_back = 0

    session_lock_timeout: Optional[str] = None
    pre_tx_session_lock_timeout: Optional[str] = None
    local_lock_timeout: Optional[str] = None
    local_lock_timeout_set: bool = False
    session_stmt_timeout: Optional[str] = None
    pre_tx_session_stmt_timeout: Optional[str] = None
    local_stmt_timeout: Optional[str] = None
    local_stmt_timeout_set: bool = False

    ever_had_lock_timeout = False
    ever_had_stmt_timeout = False
    ever_had_explicit_tx = False

    # Committed vs uncommitted constraint state for PG 12+ SET NOT NULL verification
    committed_not_valid_checks: Dict[str, str] = {}
    tx_not_valid_checks: Dict[str, str] = {}
    committed_validated_cols: Set[str] = set()
    tx_validated_cols: Set[str] = set()
    savepoint_stack: List[Any] = []

    statement_timeline: List[Dict[str, Any]] = []
    risk_score = 0

    for idx, stmt in enumerate(statements, start=1):
        norm = " ".join(stmt.split())
        upper = norm.upper()

        # 1. Check transaction control statements
        if re.match(r"^(?:BEGIN|START\s+TRANSACTION)\b", upper):
            ever_had_explicit_tx = True
            transactions_opened += 1
            if in_transaction:
                risk_score += 20
                findings.append({
                    "id": f"MIG-TXN-NESTED-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "medium",
                    "classification": "verified",
                    "lock_mode": "transaction_state",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: Nested BEGIN inside an already open transaction block",
                    "evidence": {"statement_index": idx, "in_transaction_before": True, "tx_depth": tx_depth + 1},
                    "likely_causes": ["Concatenated migration files or accidental duplicate BEGIN statement"],
                    "confidence": "high",
                    "recommendation": "Remove duplicate BEGIN or use explicit SAVEPOINT if subtransactions are intended."
                })
            if not in_transaction:
                # Snapshot pre-transaction session settings so ROLLBACK restores them accurately
                pre_tx_session_lock_timeout = session_lock_timeout
                pre_tx_session_stmt_timeout = session_stmt_timeout
                local_lock_timeout = None
                local_lock_timeout_set = False
                local_stmt_timeout = None
                local_stmt_timeout_set = False
                savepoint_stack.clear()
            in_transaction = True
            tx_depth += 1
            tx_not_valid_checks = dict(committed_not_valid_checks)
            tx_validated_cols = set(committed_validated_cols)
            statement_timeline.append({"index": idx, "type": "BEGIN", "in_transaction": in_transaction})
            continue

        if re.match(r"^(?:COMMIT|END(?:\s+TRANSACTION)?)\b", upper):
            if not in_transaction:
                risk_score += 20
                findings.append({
                    "id": f"MIG-TXN-ORPHAN-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "medium",
                    "classification": "verified",
                    "lock_mode": "transaction_state",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: COMMIT executed without an active BEGIN transaction block",
                    "evidence": {"statement_index": idx, "in_transaction_before": False},
                    "likely_causes": ["Mismatched transaction boundaries in migration script"],
                    "confidence": "high",
                    "recommendation": "Ensure every COMMIT matches a preceding BEGIN."
                })
            else:
                transactions_committed += 1
                committed_not_valid_checks = dict(tx_not_valid_checks)
                committed_validated_cols = set(tx_validated_cols)
                pre_tx_session_lock_timeout = session_lock_timeout
                pre_tx_session_stmt_timeout = session_stmt_timeout
            in_transaction = False
            tx_depth = 0
            local_lock_timeout = None
            local_lock_timeout_set = False
            local_stmt_timeout = None
            local_stmt_timeout_set = False
            savepoint_stack.clear()
            statement_timeline.append({"index": idx, "type": "COMMIT", "in_transaction": in_transaction})
            continue

        if re.match(r"^(?:ROLLBACK|ABORT)\b", upper) and not re.match(r"^(?:ROLLBACK|ABORT)(?:\s+(?:WORK|TRANSACTION))?\s+TO\b", upper):
            if not in_transaction:
                risk_score += 20
                findings.append({
                    "id": f"MIG-TXN-ORPHAN-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "medium",
                    "classification": "verified",
                    "lock_mode": "transaction_state",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: ROLLBACK executed without an active BEGIN transaction block",
                    "evidence": {"statement_index": idx, "in_transaction_before": False},
                    "likely_causes": ["Orphan ROLLBACK statement"],
                    "confidence": "high",
                    "recommendation": "Remove orphan ROLLBACK or pair it with an explicit BEGIN block."
                })
            else:
                transactions_rolled_back += 1
                # In PostgreSQL, SET [SESSION] / RESET inside a transaction is rolled back on ROLLBACK,
                # restoring session settings to their pre-transaction values!
                session_lock_timeout = pre_tx_session_lock_timeout
                session_stmt_timeout = pre_tx_session_stmt_timeout
                risk_score += 15
                findings.append({
                    "id": f"MIG-TXN-ROLLBACK-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "medium",
                    "classification": "verified",
                    "lock_mode": "transaction_state",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: Explicit ROLLBACK discards uncommitted schema/constraint and session SET changes from the current transaction",
                    "evidence": {
                        "statement_index": idx,
                        "in_transaction_before": True,
                        "restored_session_lock_timeout": session_lock_timeout,
                        "restored_session_statement_timeout": session_stmt_timeout,
                    },
                    "likely_causes": ["Dry-run rollback left in migration file or intentional abort block"],
                    "confidence": "high",
                    "recommendation": "Verify whether ROLLBACK was left in the migration file unintentionally."
                })
            in_transaction = False
            tx_depth = 0
            local_lock_timeout = None
            local_lock_timeout_set = False
            local_stmt_timeout = None
            local_stmt_timeout_set = False
            tx_not_valid_checks = dict(committed_not_valid_checks)
            tx_validated_cols = set(committed_validated_cols)
            savepoint_stack.clear()
            statement_timeline.append({"index": idx, "type": "ROLLBACK", "in_transaction": in_transaction})
            continue

        sp_create_m = re.match(r"^SAVEPOINT\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", norm, re.IGNORECASE)
        if sp_create_m:
            sp_name = sp_create_m.group(1).lower()
            if not in_transaction:
                risk_score += 20
                findings.append({
                    "id": f"MIG-TXN-SAVEPOINT-NOTX-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "medium",
                    "classification": "verified",
                    "lock_mode": "transaction_state",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: `SAVEPOINT {sp_name}` cannot be established outside a transaction block",
                    "evidence": {"statement_index": idx, "savepoint": sp_name, "in_transaction": False},
                    "likely_causes": ["SAVEPOINT requires an active BEGIN transaction block"],
                    "confidence": "high",
                    "recommendation": "Open a transaction with `BEGIN;` before declaring savepoints."
                })
            else:
                savepoint_stack.append((
                    sp_name,
                    {
                        "session_lock_timeout": session_lock_timeout,
                        "local_lock_timeout": local_lock_timeout,
                        "local_lock_timeout_set": local_lock_timeout_set,
                        "session_stmt_timeout": session_stmt_timeout,
                        "local_stmt_timeout": local_stmt_timeout,
                        "local_stmt_timeout_set": local_stmt_timeout_set,
                        "tx_not_valid_checks": dict(tx_not_valid_checks),
                        "tx_validated_cols": set(tx_validated_cols),
                    },
                ))
            statement_timeline.append({"index": idx, "type": "SAVEPOINT", "savepoint": sp_name, "in_transaction": in_transaction})
            continue

        sp_rel_m = re.match(r"^RELEASE\s+(?:SAVEPOINT\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\b", norm, re.IGNORECASE)
        if sp_rel_m:
            sp_name = sp_rel_m.group(1).lower()
            if not in_transaction:
                risk_score += 20
                findings.append({
                    "id": f"MIG-TXN-SAVEPOINT-NOTX-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "medium",
                    "classification": "verified",
                    "lock_mode": "transaction_state",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: `RELEASE SAVEPOINT {sp_name}` executed outside a transaction block",
                    "evidence": {"statement_index": idx, "savepoint": sp_name, "in_transaction": False},
                    "likely_causes": ["RELEASE SAVEPOINT requires an active transaction block"],
                    "confidence": "high",
                    "recommendation": "Ensure `RELEASE SAVEPOINT` runs inside an active `BEGIN ... COMMIT` block."
                })
            else:
                matched_idx = None
                for sp_idx in range(len(savepoint_stack) - 1, -1, -1):
                    if savepoint_stack[sp_idx][0] == sp_name:
                        matched_idx = sp_idx
                        break
                if matched_idx is not None:
                    # Releasing a savepoint also destroys all savepoints established after it
                    savepoint_stack = savepoint_stack[:matched_idx]
                else:
                    risk_score += 20
                    findings.append({
                        "id": f"MIG-TXN-SAVEPOINT-UNKNOWN-{idx:03d}",
                        "category": "transaction_hazard",
                        "severity": "medium",
                        "classification": "verified",
                        "lock_mode": "transaction_state",
                        "statement_index": idx,
                        "statement": norm[:200],
                        "title": f"Statement #{idx}: `RELEASE SAVEPOINT {sp_name}` references a non-existent or already-discarded savepoint",
                        "evidence": {"statement_index": idx, "savepoint": sp_name, "active_savepoints": [s[0] for s in savepoint_stack]},
                        "likely_causes": ["Savepoint was never created or was destroyed by an earlier ROLLBACK TO / RELEASE SAVEPOINT"],
                        "confidence": "high",
                        "recommendation": f"Define `SAVEPOINT {sp_name};` before releasing it."
                    })
            statement_timeline.append({"index": idx, "type": "RELEASE_SAVEPOINT", "savepoint": sp_name, "in_transaction": in_transaction})
            continue

        sp_rb_m = re.match(r"^(?:ROLLBACK|ABORT)(?:\s+(?:WORK|TRANSACTION))?\s+TO\s+(?:SAVEPOINT\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\b", norm, re.IGNORECASE)
        if sp_rb_m:
            sp_name = sp_rb_m.group(1).lower()
            if not in_transaction:
                risk_score += 20
                findings.append({
                    "id": f"MIG-TXN-SAVEPOINT-NOTX-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "medium",
                    "classification": "verified",
                    "lock_mode": "transaction_state",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: `ROLLBACK TO SAVEPOINT {sp_name}` executed outside a transaction block",
                    "evidence": {"statement_index": idx, "savepoint": sp_name, "in_transaction": False},
                    "likely_causes": ["ROLLBACK TO SAVEPOINT requires an active transaction block"],
                    "confidence": "high",
                    "recommendation": "Ensure `ROLLBACK TO SAVEPOINT` runs inside an active `BEGIN ... COMMIT` block."
                })
            else:
                matched_idx = None
                for sp_idx in range(len(savepoint_stack) - 1, -1, -1):
                    if savepoint_stack[sp_idx][0] == sp_name:
                        matched_idx = sp_idx
                        break
                if matched_idx is not None:
                    snap = savepoint_stack[matched_idx][1]
                    session_lock_timeout = snap["session_lock_timeout"]
                    local_lock_timeout = snap["local_lock_timeout"]
                    local_lock_timeout_set = snap["local_lock_timeout_set"]
                    session_stmt_timeout = snap["session_stmt_timeout"]
                    local_stmt_timeout = snap["local_stmt_timeout"]
                    local_stmt_timeout_set = snap["local_stmt_timeout_set"]
                    tx_not_valid_checks = dict(snap["tx_not_valid_checks"])
                    tx_validated_cols = set(snap["tx_validated_cols"])
                    # Rolling back to sp_name destroys all savepoints established after sp_name, while keeping sp_name valid
                    savepoint_stack = savepoint_stack[: matched_idx + 1]
                else:
                    risk_score += 20
                    session_lock_timeout = pre_tx_session_lock_timeout
                    session_stmt_timeout = pre_tx_session_stmt_timeout
                    local_lock_timeout = None
                    local_lock_timeout_set = False
                    local_stmt_timeout = None
                    local_stmt_timeout_set = False
                    findings.append({
                        "id": f"MIG-TXN-SAVEPOINT-UNKNOWN-{idx:03d}",
                        "category": "transaction_hazard",
                        "severity": "medium",
                        "classification": "verified",
                        "lock_mode": "transaction_state",
                        "statement_index": idx,
                        "statement": norm[:200],
                        "title": f"Statement #{idx}: `ROLLBACK TO SAVEPOINT {sp_name}` references a non-existent or already-discarded savepoint",
                        "evidence": {"statement_index": idx, "savepoint": sp_name, "active_savepoints": [s[0] for s in savepoint_stack]},
                        "likely_causes": ["Savepoint was never created or was destroyed by an earlier ROLLBACK TO / RELEASE SAVEPOINT"],
                        "confidence": "high",
                        "recommendation": f"Ensure `SAVEPOINT {sp_name};` is active before rolling back to it."
                    })
            restored_eff_lock = local_lock_timeout if (in_transaction and local_lock_timeout_set) else session_lock_timeout
            restored_eff_stmt = local_stmt_timeout if (in_transaction and local_stmt_timeout_set) else session_stmt_timeout
            statement_timeline.append({
                "index": idx,
                "type": "ROLLBACK_TO_SAVEPOINT",
                "savepoint": sp_name,
                "in_transaction": in_transaction,
                "effective_lock_timeout": restored_eff_lock,
                "effective_statement_timeout": restored_eff_stmt,
            })
            continue

        if re.match(r"^RESET\s+ALL\b", upper):
            session_lock_timeout = None
            session_stmt_timeout = None
            if in_transaction:
                local_lock_timeout = None
                local_lock_timeout_set = False
                local_stmt_timeout = None
                local_stmt_timeout_set = False
            else:
                pre_tx_session_lock_timeout = None
                pre_tx_session_stmt_timeout = None
            statement_timeline.append({
                "index": idx,
                "type": "RESET_ALL",
                "in_transaction": in_transaction,
                "effective_lock_timeout": None,
                "effective_statement_timeout": None,
            })
            continue

        if re.match(r"^RESET\s+LOCK_TIMEOUT\b", upper):
            session_lock_timeout = None
            if in_transaction:
                local_lock_timeout = None
                local_lock_timeout_set = False
            else:
                pre_tx_session_lock_timeout = None
            statement_timeline.append({
                "index": idx,
                "type": "RESET_LOCK_TIMEOUT",
                "in_transaction": in_transaction,
                "effective_lock_timeout": None,
                "effective_statement_timeout": local_stmt_timeout if (in_transaction and local_stmt_timeout_set) else session_stmt_timeout,
            })
            continue

        if re.match(r"^RESET\s+STATEMENT_TIMEOUT\b", upper):
            session_stmt_timeout = None
            if in_transaction:
                local_stmt_timeout = None
                local_stmt_timeout_set = False
            else:
                pre_tx_session_stmt_timeout = None
            statement_timeline.append({
                "index": idx,
                "type": "RESET_STATEMENT_TIMEOUT",
                "in_transaction": in_transaction,
                "effective_lock_timeout": local_lock_timeout if (in_transaction and local_lock_timeout_set) else session_lock_timeout,
                "effective_statement_timeout": None,
            })
            continue

        # 2. Check SET [LOCAL | SESSION] lock_timeout / statement_timeout
        lt_m = re.match(r"^SET\s+(LOCAL\s+|SESSION\s+)?lock_timeout\s*(?:=|TO)\s*(.+)$", norm, re.IGNORECASE)
        if lt_m:
            scope = (lt_m.group(1) or "").strip().upper()
            val = lt_m.group(2).strip()
            active = _is_nonzero_timeout(val)
            if scope == "LOCAL":
                if not in_transaction:
                    risk_score += 20
                    findings.append({
                        "id": f"MIG-TIMEOUT-LOCAL-NOTX-{idx:03d}",
                        "category": "lock_queue_hazard",
                        "severity": "high",
                        "classification": "verified",
                        "lock_mode": "configuration_error",
                        "statement_index": idx,
                        "statement": norm[:200],
                        "title": f"Statement #{idx}: `SET LOCAL lock_timeout` executed outside a transaction block has no effect on subsequent statements",
                        "evidence": {"statement_index": idx, "in_transaction": False, "value": val},
                        "likely_causes": ["SET LOCAL only persists until the end of the current transaction; outside BEGIN...COMMIT it resets immediately"],
                        "confidence": "high",
                        "recommendation": "Use `SET lock_timeout = '2s';` (session-level) or wrap the transactional DDL in `BEGIN; SET LOCAL lock_timeout = '2s'; ... COMMIT;`."
                    })
                else:
                    local_lock_timeout_set = True
                    local_lock_timeout = val if active else None
                    if active:
                        ever_had_lock_timeout = True
            else:
                session_lock_timeout = val if active else None
                if in_transaction:
                    local_lock_timeout_set = False
                    local_lock_timeout = None
                else:
                    pre_tx_session_lock_timeout = session_lock_timeout
                if active:
                    ever_had_lock_timeout = True
            statement_timeline.append({"index": idx, "type": "SET_LOCK_TIMEOUT", "scope": scope or "SESSION", "value": val, "in_transaction": in_transaction})
            continue

        st_m = re.match(r"^SET\s+(LOCAL\s+|SESSION\s+)?statement_timeout\s*(?:=|TO)\s*(.+)$", norm, re.IGNORECASE)
        if st_m:
            scope = (st_m.group(1) or "").strip().upper()
            val = st_m.group(2).strip()
            active = _is_nonzero_timeout(val)
            if scope == "LOCAL":
                if not in_transaction:
                    risk_score += 15
                    findings.append({
                        "id": f"MIG-STMTTIMEOUT-LOCAL-NOTX-{idx:03d}",
                        "category": "lock_queue_hazard",
                        "severity": "medium",
                        "classification": "verified",
                        "lock_mode": "configuration_error",
                        "statement_index": idx,
                        "statement": norm[:200],
                        "title": f"Statement #{idx}: `SET LOCAL statement_timeout` executed outside a transaction block has no effect",
                        "evidence": {"statement_index": idx, "in_transaction": False, "value": val},
                        "likely_causes": ["SET LOCAL resets immediately when not inside an open transaction block"],
                        "confidence": "high",
                        "recommendation": "Use session-level `SET statement_timeout = '30s';` or place `SET LOCAL` inside `BEGIN ... COMMIT`."
                    })
                else:
                    local_stmt_timeout_set = True
                    local_stmt_timeout = val if active else None
                    if active:
                        ever_had_stmt_timeout = True
            else:
                session_stmt_timeout = val if active else None
                if in_transaction:
                    local_stmt_timeout_set = False
                    local_stmt_timeout = None
                else:
                    pre_tx_session_stmt_timeout = session_stmt_timeout
                if active:
                    ever_had_stmt_timeout = True
            statement_timeline.append({"index": idx, "type": "SET_STATEMENT_TIMEOUT", "scope": scope or "SESSION", "value": val, "in_transaction": in_transaction})
            continue

        # Compute effective timeouts active AT THIS EXACT STATEMENT POSITION
        effective_lock_timeout = local_lock_timeout if (in_transaction and local_lock_timeout_set) else session_lock_timeout
        effective_stmt_timeout = local_stmt_timeout if (in_transaction and local_stmt_timeout_set) else session_stmt_timeout
        active_not_valid_checks = tx_not_valid_checks if in_transaction else committed_not_valid_checks
        active_validated_cols = tx_validated_cols if in_transaction else committed_validated_cols

        # 3. Check ambiguous / procedural constructs
        if re.match(r"^(?:DO\b|CALL\b|PREPARE\s+TRANSACTION\b|EXECUTE\b)", upper):
            risk_score += 15
            findings.append({
                "id": f"MIG-UNCERTAIN-{idx:03d}",
                "category": "ambiguous_construct",
                "severity": "medium",
                "classification": "heuristic",
                "lock_mode": "unknown_procedural",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: Procedural or dynamic SQL construct cannot be statically proven lock-safe",
                "evidence": {"statement_index": idx, "in_transaction": in_transaction, "effective_lock_timeout": effective_lock_timeout},
                "likely_causes": ["DO/CALL/EXECUTE/SAVEPOINT blocks may execute dynamic DDL or hold locks unpredictably"],
                "confidence": "medium",
                "recommendation": "Audit procedural migration blocks manually and enforce explicit lock_timeout inside the block."
            })

        # 4. Track ADD CONSTRAINT <name> CHECK (<col> IS NOT NULL) NOT VALID
        chk_m = re.search(
            r"\bADD\s+CONSTRAINT\s+([a-zA-Z0-9_]+)\s+CHECK\s*\(\s*([a-zA-Z0-9_]+)\s+IS\s+NOT\s+NULL\s*\)\s+NOT\s+VALID\b",
            norm,
            re.IGNORECASE,
        )
        if chk_m:
            active_not_valid_checks[chk_m.group(1).lower()] = chk_m.group(2).lower()
            findings.append({
                "id": f"MIG-CHK-NV-{idx:03d}",
                "category": "share_update_exclusive",
                "severity": "info",
                "classification": "verified",
                "lock_mode": "SHARE UPDATE EXCLUSIVE / brief metadata lock",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: Safe two-step NOT VALID check constraint `{chk_m.group(1)}` added on `{chk_m.group(2)}`",
                "evidence": {"constraint": chk_m.group(1), "column": chk_m.group(2), "in_transaction": in_transaction},
                "likely_causes": ["Zero-downtime NOT NULL preparation"],
                "confidence": "high",
                "recommendation": f"Validate with `ALTER TABLE ... VALIDATE CONSTRAINT {chk_m.group(1)};` before running SET NOT NULL."
            })

        val_m = re.search(r"\bVALIDATE\s+CONSTRAINT\s+([a-zA-Z0-9_]+)\b", norm, re.IGNORECASE)
        if val_m:
            cname = val_m.group(1).lower()
            if cname in active_not_valid_checks:
                active_validated_cols.add(active_not_valid_checks[cname])

        # 5. Check whether this statement is a lock-sensitive DDL operation that requires an active lock_timeout BEFORE it executes
        is_lock_sensitive_ddl = bool(
            re.search(r"\b(?:ALTER\s+TABLE|DROP\s+TABLE|TRUNCATE|LOCK\s+TABLE|VACUUM\s+FULL|CLUSTER)\b", upper)
            or (re.search(r"\b(?:CREATE|DROP|REINDEX)\s+(?:UNIQUE\s+)?INDEX\b", upper) and "CONCURRENTLY" not in upper)
            or (re.search(r"\bREFRESH\s+MATERIALIZED\s+VIEW\b", upper) and "CONCURRENTLY" not in upper)
        )
        # Note: ALTER TABLE ... VALIDATE CONSTRAINT acquires SHARE UPDATE EXCLUSIVE, which still benefits from lock_timeout, whereas CREATE INDEX CONCURRENTLY waits calmly without blocking reads/writes.
        if is_lock_sensitive_ddl and not effective_lock_timeout:
            risk_score += 15
            findings.append({
                "id": f"MIG-TIMEOUT-{idx:03d}",
                "category": "lock_queue_hazard",
                "severity": "medium",
                "classification": "verified",
                "lock_mode": "lock_queue_amplification",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: Lock-sensitive DDL executes without an active `lock_timeout` in effect at this position",
                "evidence": {
                    "statement_index": idx,
                    "in_transaction": in_transaction,
                    "effective_lock_timeout": effective_lock_timeout,
                    "effective_statement_timeout": effective_stmt_timeout,
                },
                "likely_causes": [
                    "No SET lock_timeout was executed prior to this statement (or a prior SET LOCAL lock_timeout expired on COMMIT/ROLLBACK)"
                ],
                "confidence": "high",
                "recommendation": "Configure `SET lock_timeout = '2s';` (or `SET LOCAL lock_timeout = '2s';` inside the current transaction) BEFORE executing DDL."
            })

        # 6. Non-concurrent index creation
        if re.search(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b", upper) and "CONCURRENTLY" not in upper:
            risk_score += 30
            findings.append({
                "id": f"MIG-IDX-{idx:03d}",
                "category": "locking",
                "severity": "high",
                "classification": "verified",
                "lock_mode": "SHARE (blocks writes)",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: CREATE INDEX without CONCURRENTLY acquires a SHARE lock that blocks all writes",
                "evidence": {"concurrently": False, "in_transaction": in_transaction, "lock_mode": "SHARE"},
                "likely_causes": ["Standard CREATE INDEX holds SHARE lock for the entire index build"],
                "confidence": "high",
                "recommendation": "Rewrite as CREATE INDEX CONCURRENTLY outside of a transaction block."
            })

        # 7. Non-concurrent DROP INDEX
        if re.search(r"\bDROP\s+INDEX\b", upper) and "CONCURRENTLY" not in upper:
            risk_score += 25
            findings.append({
                "id": f"MIG-DROPIDX-{idx:03d}",
                "category": "locking",
                "severity": "high",
                "classification": "verified",
                "lock_mode": "ACCESS EXCLUSIVE (blocks reads and writes)",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: DROP INDEX without CONCURRENTLY acquires an ACCESS EXCLUSIVE lock",
                "evidence": {"concurrently": False, "lock_mode": "ACCESS EXCLUSIVE", "in_transaction": in_transaction},
                "likely_causes": ["Standard DROP INDEX blocks concurrent reads and writes"],
                "confidence": "high",
                "recommendation": "Use DROP INDEX CONCURRENTLY outside a transaction block."
            })

        # 8. CONCURRENTLY operation evaluated against the CURRENT transaction state at statement `idx`
        if "CONCURRENTLY" in upper and re.search(r"\b(?:CREATE|DROP|REINDEX)\s+(?:UNIQUE\s+)?INDEX\b|\bDETACH\s+PARTITION\b", upper):
            if in_transaction:
                risk_score += 40
                findings.append({
                    "id": f"MIG-TXN-{idx:03d}",
                    "category": "transaction_hazard",
                    "severity": "critical",
                    "classification": "verified",
                    "lock_mode": "SHARE UPDATE EXCLUSIVE",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: CONCURRENTLY operation inside an open BEGIN transaction block will fail at runtime",
                    "evidence": {"in_transaction_at_statement": True, "has_concurrently": True, "statement_index": idx},
                    "likely_causes": ["PostgreSQL prohibits CONCURRENTLY index/partition operations inside explicit transaction blocks"],
                    "confidence": "high",
                    "recommendation": "Commit the preceding transaction (`COMMIT;`) before executing CONCURRENTLY statements, or move them to a non-transactional migration file."
                })

        # 9. ALTER COLUMN TYPE (table rewrite)
        if re.search(r"\bALTER\s+TABLE\b.*\bALTER\s+(?:COLUMN\s+)?\w+\s+(?:SET\s+DATA\s+)?TYPE\b", upper):
            risk_score += 40
            findings.append({
                "id": f"MIG-REWRITE-{idx:03d}",
                "category": "table_rewrite",
                "severity": "critical",
                "classification": "verified",
                "lock_mode": "ACCESS EXCLUSIVE (blocks reads and writes)",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: ALTER COLUMN TYPE acquires ACCESS EXCLUSIVE lock and triggers a full table rewrite",
                "evidence": {"operation": "ALTER COLUMN TYPE", "pg_version": pg_version, "in_transaction": in_transaction},
                "likely_causes": ["Changing column physical representation rewrites every heap page under ACCESS EXCLUSIVE lock"],
                "confidence": "high",
                "recommendation": "Use expand-and-contract: add a new column, dual-write via trigger or application, backfill in small batches, and swap."
            })

        # 10. ADD COLUMN with volatile default, < PG 11 default, or inline PRIMARY KEY / UNIQUE
        if re.search(r"\bALTER\s+TABLE\b.*\bADD\s+(?:COLUMN\s+)?", upper):
            has_default = "DEFAULT" in upper
            volatile_default = bool(re.search(r"DEFAULT\s+(?:RANDOM|GEN_RANDOM_UUID|UUID_GENERATE|CLOCK_TIMESTAMP|TIMEOFDAY)\s*\(", upper))
            inline_pk_unique = bool(re.search(r"\bADD\s+(?:COLUMN\s+)?\w+\s+\w+.*\b(?:PRIMARY\s+KEY|UNIQUE)\b", upper))
            if (has_default and (volatile_default or pg_version < 11)) or inline_pk_unique:
                risk_score += 35
                findings.append({
                    "id": f"MIG-ADDCOL-{idx:03d}",
                    "category": "table_rewrite",
                    "severity": "high",
                    "classification": "verified",
                    "lock_mode": "ACCESS EXCLUSIVE",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": (
                        f"Statement #{idx}: ADD COLUMN with {'inline PRIMARY KEY/UNIQUE' if inline_pk_unique else ('volatile' if volatile_default else 'PG < 11') + ' DEFAULT'} causes table rewrite or blocking index build"
                    ),
                    "evidence": {"pg_version": pg_version, "volatile_default": volatile_default, "inline_pk_unique": inline_pk_unique},
                    "likely_causes": ["Volatile defaults, inline unique constraints, or PostgreSQL < 11 cannot complete in catalog metadata alone"],
                    "confidence": "high",
                    "recommendation": "Add the column as nullable without a default, backfill in batched UPDATEs, create unique index CONCURRENTLY, and set DEFAULT."
                })

        # 11. SET NOT NULL directly without validated CHECK constraint at this position
        snn_m = re.search(r"\bALTER\s+TABLE\b.*\bALTER\s+(?:COLUMN\s+)?([a-zA-Z0-9_]+)\s+SET\s+NOT\s+NULL\b", norm, re.IGNORECASE)
        if snn_m:
            col = snn_m.group(1).lower()
            safe_pg12_not_null = pg_version >= 12 and col in active_validated_cols
            if not safe_pg12_not_null:
                risk_score += 25
                findings.append({
                    "id": f"MIG-NOTNULL-{idx:03d}",
                    "category": "locking",
                    "severity": "high",
                    "classification": "verified",
                    "lock_mode": "ACCESS EXCLUSIVE",
                    "statement_index": idx,
                    "statement": norm[:200],
                    "title": f"Statement #{idx}: ALTER COLUMN `{col}` SET NOT NULL performs a full sequential scan under ACCESS EXCLUSIVE lock",
                    "evidence": {
                        "column": col,
                        "pg_version": pg_version,
                        "backed_by_validated_check": col in active_validated_cols,
                    },
                    "likely_causes": [
                        "PostgreSQL < 12 always scans the table for SET NOT NULL; PostgreSQL 12+ requires a preceding validated CHECK (col IS NOT NULL) constraint to skip the scan"
                    ],
                    "confidence": "high",
                    "recommendation": f"Add `CHECK ({col} IS NOT NULL) NOT VALID`, run `VALIDATE CONSTRAINT` (`SHARE UPDATE EXCLUSIVE`), and then run `SET NOT NULL` on PostgreSQL 12+."
                })

        # 12. ADD CONSTRAINT FOREIGN KEY or CHECK without NOT VALID
        if re.search(r"\bALTER\s+TABLE\b.*\bADD\s+CONSTRAINT\b.*\b(?:FOREIGN\s+KEY|CHECK)\b", upper) and "NOT VALID" not in upper:
            risk_score += 25
            findings.append({
                "id": f"MIG-FK-{idx:03d}",
                "category": "locking",
                "severity": "high",
                "classification": "verified",
                "lock_mode": "SHARE ROW EXCLUSIVE / ACCESS EXCLUSIVE",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: Adding FOREIGN KEY or CHECK constraint without NOT VALID validates all existing rows under heavy lock",
                "evidence": {"not_valid_present": False, "statement_index": idx},
                "likely_causes": ["Immediate constraint validation scans the table while blocking concurrent writes"],
                "confidence": "high",
                "recommendation": "Append NOT VALID to ADD CONSTRAINT, then execute ALTER TABLE ... VALIDATE CONSTRAINT (`SHARE UPDATE EXCLUSIVE`) in a separate step."
            })

        # 13. Partition ATTACH / DETACH version-aware locking
        if re.search(r"\bALTER\s+TABLE\b.*\bDETACH\s+PARTITION\b", upper) and ("CONCURRENTLY" not in upper or pg_version < 14):
            risk_score += 20
            findings.append({
                "id": f"MIG-PART-{idx:03d}",
                "category": "locking",
                "severity": "medium",
                "classification": "verified",
                "lock_mode": "ACCESS EXCLUSIVE",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: DETACH PARTITION without CONCURRENTLY (or on PG < 14) acquires ACCESS EXCLUSIVE lock on parent table",
                "evidence": {"pg_version": pg_version, "concurrently": "CONCURRENTLY" in upper},
                "likely_causes": ["PostgreSQL 14+ added DETACH PARTITION CONCURRENTLY to downgrade parent lock to SHARE UPDATE EXCLUSIVE"],
                "confidence": "high",
                "recommendation": "On PostgreSQL 14+, use `ALTER TABLE ... DETACH PARTITION ... CONCURRENTLY` outside a transaction block."
            })

        # 14. Destructive DROP TABLE / DROP COLUMN / TRUNCATE
        if re.search(r"\b(?:DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE)\b", upper) or (re.search(r"\bALTER\s+TABLE\b", upper) and " DROP " in f" {upper} "):
            risk_score += 25
            findings.append({
                "id": f"MIG-DESTRUCT-{idx:03d}",
                "category": "destructive_change",
                "severity": "high",
                "classification": "verified",
                "lock_mode": "ACCESS EXCLUSIVE",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: Destructive schema operation (DROP/TRUNCATE) detected; breaks running application instances referencing the column/table",
                "evidence": {"destructive": True, "statement_index": idx},
                "likely_causes": ["Dropping columns or tables while old application code is still deployed causes immediate query failures and irreversible data loss"],
                "confidence": "high",
                "recommendation": "Deploy application code removing all references to the column first, verify zero queries reference it, and drop in a subsequent release."
            })

        # 15. VACUUM FULL / CLUSTER / LOCK TABLE / non-concurrent REFRESH MATERIALIZED VIEW
        if re.search(r"\b(?:VACUUM\s+FULL|CLUSTER)\b", upper):
            risk_score += 40
            findings.append({
                "id": f"MIG-REWRITE-{idx:03d}",
                "category": "table_rewrite",
                "severity": "critical",
                "classification": "verified",
                "lock_mode": "ACCESS EXCLUSIVE (blocks reads and writes)",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: `VACUUM FULL` or `CLUSTER` acquires ACCESS EXCLUSIVE lock and rewrites the entire table",
                "evidence": {"statement_index": idx, "in_transaction": in_transaction},
                "likely_causes": ["VACUUM FULL and CLUSTER hold ACCESS EXCLUSIVE lock for the entire table copy"],
                "confidence": "high",
                "recommendation": "Use standard `VACUUM (VERBOSE, ANALYZE)` or `pg_repack` for online bloat removal."
            })

        if re.search(r"\bLOCK\s+TABLE\b", upper) or (re.search(r"\bREFRESH\s+MATERIALIZED\s+VIEW\b", upper) and "CONCURRENTLY" not in upper):
            risk_score += 30
            findings.append({
                "id": f"MIG-LOCK-{idx:03d}",
                "category": "locking",
                "severity": "high",
                "classification": "verified",
                "lock_mode": "ACCESS EXCLUSIVE",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Statement #{idx}: Explicit `LOCK TABLE` or non-concurrent `REFRESH MATERIALIZED VIEW` blocks concurrent traffic",
                "evidence": {"statement_index": idx, "in_transaction": in_transaction},
                "likely_causes": ["Explicit table locking or non-concurrent matview refresh blocks reads/writes"],
                "confidence": "high",
                "recommendation": "Use `REFRESH MATERIALIZED VIEW CONCURRENTLY` (requires unique index) and avoid explicit `LOCK TABLE` in online migrations."
            })

        statement_timeline.append({
            "index": idx,
            "statement": norm[:120],
            "in_transaction": in_transaction,
            "effective_lock_timeout": effective_lock_timeout,
            "effective_statement_timeout": effective_stmt_timeout,
        })

    # Check unclosed transaction at EOF
    if in_transaction:
        risk_score += 30
        findings.append({
            "id": "MIG-TXN-UNCLOSED",
            "category": "transaction_hazard",
            "severity": "high",
            "classification": "verified",
            "lock_mode": "transaction_state",
            "statement_index": len(statements),
            "statement": "(end of migration)",
            "title": "Unclosed transaction block at end of migration (BEGIN without matching COMMIT or ROLLBACK)",
            "evidence": {"in_transaction_at_eof": True, "transactions_opened": transactions_opened, "transactions_committed": transactions_committed},
            "likely_causes": ["Missing COMMIT; at the end of the migration file"],
            "confidence": "high",
            "recommendation": "Add an explicit `COMMIT;` to close the transaction block."
        })

    non_info_findings = [f for f in findings if f["severity"] != "info"]
    if risk_score >= 50 or any(f["severity"] == "critical" for f in findings):
        status = "critical"
        risk_level = "CRITICAL"
    elif risk_score >= 25 or any(f["severity"] == "high" for f in findings):
        status = "warning"
        risk_level = "HIGH"
    elif risk_score > 0 or non_info_findings:
        status = "warning"
        risk_level = "MEDIUM"
    else:
        status = "ok"
        risk_level = "LOW"
        findings.append({
            "id": "MIG-OK-001",
            "category": "migration_safety",
            "severity": "info",
            "classification": "verified",
            "lock_mode": "safe",
            "statement_index": 0,
            "statement": "(all statements)",
            "title": "Migration statements follow safe zero-downtime PostgreSQL patterns in execution order",
            "evidence": {
                "statement_count": len(statements),
                "has_lock_timeout": ever_had_lock_timeout,
                "pg_version": pg_version,
            },
            "likely_causes": ["All lock-sensitive statements are guarded by preceding lock_timeout and safe concurrency rules"],
            "confidence": "high",
            "recommendation": "Proceed with standard staging verification and rollback check."
        })

    for f in findings:
        if f["recommendation"] not in recommendations:
            recommendations.append(f["recommendation"])

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version(), "target_pg_version": str(pg_version)},
        "findings": findings,
        "metrics": {
            "parser_engine": "sequential_state_machine_sql_analyzer",
            "statement_count": len(statements),
            "risk_score": min(100, risk_score),
            "risk_classification": risk_level,
            "has_explicit_transaction": ever_had_explicit_tx,
            "in_transaction_at_eof": in_transaction,
            "transactions_opened": transactions_opened,
            "transactions_committed": transactions_committed,
            "transactions_rolled_back": transactions_rolled_back,
            "has_lock_timeout": ever_had_lock_timeout,
            "has_statement_timeout": ever_had_stmt_timeout,
            "validated_not_null_columns": sorted(committed_validated_cols),
            "statement_timeline": statement_timeline,
        },
        "warnings": warnings,
        "recommendations": recommendations,
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze PostgreSQL migration SQL for lock and rewrite hazards.")
    parser.add_argument("--sql-file", required=True, help="Path to SQL migration file")
    parser.add_argument("--pg-version", type=int, default=16, help="Target PostgreSQL major version (default: 16)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.sql_file)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"SQL file not found: {p}", args.pg_version)), file=sys.stderr)
        return 1

    sql_text = p.read_text(encoding="utf-8", errors="replace")
    if not sql_text.strip():
        print(json.dumps(make_error_envelope("SQL file is empty", args.pg_version)), file=sys.stderr)
        return 2

    payload = analyze_migration_sql(sql_text, pg_version=args.pg_version)
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
