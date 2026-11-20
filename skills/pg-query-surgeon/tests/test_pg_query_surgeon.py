import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
EXAMPLES_DIR = REPO_ROOT / "examples"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
SCHEMA_PATH = REPO_ROOT / "schemas" / "pg-query-surgeon.schema.json"

sys.path.insert(0, str(SCRIPTS_DIR))
import analyze_explain
import analyze_sql
import check_migration_safety
import generate_migration_report
import index_advisor
import inspect_schema
from common import run_bounded_command, run_readonly_psql_query, split_sql_statements, validate_against_schema


class TestPgQuerySurgeon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def assertValidSchema(self, payload):
        errs = validate_against_schema(payload, self.schema)
        self.assertEqual(errs, [], f"JSON Schema validation errors: {errs}")

    def test_lexical_sql_splitter_handles_quotes_comments_and_dollar_quoting(self):
        complex_sql = """
        -- Header comment with ; semicolon
        /* Block comment with ; semicolon */
        INSERT INTO logs (msg) VALUES ('hello; world');
        CREATE FUNCTION test_fn() RETURNS void AS $body$
        BEGIN
            PERFORM 1;
            PERFORM 2;
        END;
        $body$ LANGUAGE plpgsql;
        SELECT 1;
        """
        stmts = split_sql_statements(complex_sql)
        self.assertEqual(len(stmts), 3)
        self.assertIn("'hello; world'", stmts[0])
        self.assertIn("$body$", stmts[1])

    def test_migration_safety_detects_all_hazards_and_redacts_secrets(self):
        sql = (EXAMPLES_DIR / "unsafe_migration.sql").read_text(encoding="utf-8")
        res = check_migration_safety.analyze_migration_sql(sql, pg_version=16)
        self.assertValidSchema(res)
        self.assertEqual(res["status"], "critical")
        self.assertEqual(res["metrics"]["risk_classification"], "CRITICAL")
        cats = {f["category"] for f in res["findings"]}
        self.assertIn("locking", cats)
        self.assertIn("transaction_hazard", cats)
        self.assertIn("table_rewrite", cats)
        self.assertIn("destructive_change", cats)
        self.assertIn("lock_queue_hazard", cats)
        dumped = json.dumps(res)
        self.assertNotIn("SuperSecretPass123!", dumped)

    def test_pg12_safe_not_null_with_validated_check_constraint(self):
        safe_nn_sql = """
        SET lock_timeout = '2s';
        ALTER TABLE orders ADD CONSTRAINT chk_orders_addr_nn CHECK (shipping_address IS NOT NULL) NOT VALID;
        ALTER TABLE orders VALIDATE CONSTRAINT chk_orders_addr_nn;
        ALTER TABLE orders ALTER COLUMN shipping_address SET NOT NULL;
        """
        res_pg16 = check_migration_safety.analyze_migration_sql(safe_nn_sql, pg_version=16)
        self.assertValidSchema(res_pg16)
        self.assertEqual(res_pg16["status"], "ok")

        res_pg11 = check_migration_safety.analyze_migration_sql(safe_nn_sql, pg_version=11)
        self.assertValidSchema(res_pg11)
        self.assertEqual(res_pg11["status"], "warning")

    def test_pg_version_10_vs_16_add_column_default(self):
        ddl = "SET lock_timeout = '2s'; ALTER TABLE items ADD COLUMN status TEXT DEFAULT 'active';"
        res_pg16 = check_migration_safety.analyze_migration_sql(ddl, pg_version=16)
        res_pg10 = check_migration_safety.analyze_migration_sql(ddl, pg_version=10)
        self.assertValidSchema(res_pg16)
        self.assertValidSchema(res_pg10)
        self.assertEqual(res_pg16["status"], "ok")
        self.assertEqual(res_pg10["status"], "warning")

    def test_sql_anti_patterns_and_n_plus_one(self):
        sql = (EXAMPLES_DIR / "slow_queries.sql").read_text(encoding="utf-8")
        res = analyze_sql.analyze_queries(sql)
        self.assertValidSchema(res)
        self.assertEqual(res["status"], "warning")
        cats = {f["category"] for f in res["findings"]}
        self.assertIn("index_prevented", cats)
        self.assertIn("sargability", cats)
        self.assertIn("pagination", cats)
        self.assertIn("join_efficiency", cats)
        self.assertIn("n_plus_one", cats)

    def test_explain_analyzer_json_and_text_formats(self):
        raw = json.loads((EXAMPLES_DIR / "slow_explain_plan.json").read_text(encoding="utf-8"))
        res_json = analyze_explain.analyze_explain_json(raw)
        self.assertValidSchema(res_json)
        self.assertEqual(res_json["status"], "warning")

        txt_plan = (FIXTURES_DIR / "text_explain_plan.txt").read_text(encoding="utf-8")
        res_txt = analyze_explain.analyze_explain_content(txt_plan)
        self.assertValidSchema(res_txt)
        self.assertEqual(res_txt["status"], "warning")
        cats = {f["category"] for f in res_txt["findings"]}
        self.assertIn("sequential_scan", cats)
        self.assertIn("cardinality_misestimate", cats)
        self.assertIn("memory_spill", cats)

    def test_malformed_explain_returns_valid_error_schema(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "analyze_explain.py"), "--explain-file", str(EXAMPLES_DIR / "schema.sql")],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(proc.returncode, 2)
        err = json.loads(proc.stderr)
        self.assertValidSchema(err)
        self.assertEqual(err["status"], "error")

    def test_schema_and_catalog_snapshot_inspector(self):
        sch = (EXAMPLES_DIR / "schema.sql").read_text(encoding="utf-8")
        cat = json.loads((FIXTURES_DIR / "pg_catalog_snapshot.json").read_text(encoding="utf-8"))
        res = inspect_schema.inspect_schema_sql(sch, cat)
        self.assertValidSchema(res)
        self.assertEqual(res["status"], "warning")
        ids = {f["id"] for f in res["findings"]}
        self.assertIn("SCH-PK-AUDIT_EVENTS", ids)
        self.assertIn("SCH-FKIDX-ORDERS-MERCHANT_ID", ids)
        self.assertIn("CAT-BLOAT-ORDERS", ids)
        self.assertIn("CAT-INVIDX-IDX_ORDERS_FAILED_CONCURRENT", ids)
        self.assertIn("CAT-IDLETX-8821", ids)
        self.assertIn("CAT-LOCKWAIT-8845", ids)

    def test_readonly_psql_guard_blocks_mutating_sql(self):
        res = run_readonly_psql_query("postgresql://u:secret@localhost/db", "DROP TABLE orders;")
        self.assertFalse(res["ok"])
        self.assertIn("Refusing non-SELECT", res["error"])

    def test_index_advisor_and_full_report_schema(self):
        rep = generate_migration_report.generate_full_report(
            EXAMPLES_DIR / "unsafe_migration.sql",
            EXAMPLES_DIR / "slow_queries.sql",
            EXAMPLES_DIR / "slow_explain_plan.json",
            EXAMPLES_DIR / "schema.sql",
            pg_version=16,
        )
        self.assertValidSchema(rep)
        self.assertEqual(rep["status"], "critical")
        md = generate_migration_report.render_markdown(rep)
        self.assertIn("CREATE INDEX CONCURRENTLY", md)


    def test_regression_01_and_02_lock_timeout_ordering(self):
        # 1. Lock timeout before risky DDL -> LOW / ok
        sql_before = (FIXTURES_DIR / "mig_01_timeout_before_ddl.sql").read_text(encoding="utf-8")
        res_before = check_migration_safety.analyze_migration_sql(sql_before, pg_version=16)
        self.assertValidSchema(res_before)
        self.assertEqual(res_before["status"], "ok")
        self.assertEqual(res_before["metrics"]["risk_classification"], "LOW")

        # 2. Lock timeout AFTER risky DDL -> MEDIUM / warning with MIG-TIMEOUT-001 on statement 1
        sql_after = (FIXTURES_DIR / "mig_02_timeout_after_ddl.sql").read_text(encoding="utf-8")
        res_after = check_migration_safety.analyze_migration_sql(sql_after, pg_version=16)
        self.assertValidSchema(res_after)
        self.assertEqual(res_after["status"], "warning")
        self.assertEqual(res_after["metrics"]["risk_classification"], "MEDIUM")
        ids = {f["id"]: f for f in res_after["findings"]}
        self.assertIn("MIG-TIMEOUT-001", ids)
        self.assertEqual(ids["MIG-TIMEOUT-001"]["statement_index"], 1)

    def test_regression_03_and_04_transaction_local_vs_session_timeout(self):
        # 3. SET LOCAL lock_timeout protects statement 3 inside BEGIN..COMMIT, but expires on COMMIT so statement 5 is flagged
        sql_local = (FIXTURES_DIR / "mig_03_tx_local_timeout.sql").read_text(encoding="utf-8")
        res_local = check_migration_safety.analyze_migration_sql(sql_local, pg_version=16)
        self.assertValidSchema(res_local)
        self.assertEqual(res_local["status"], "warning")
        ids = {f["id"] for f in res_local["findings"]}
        self.assertNotIn("MIG-TIMEOUT-003", ids)
        self.assertIn("MIG-TIMEOUT-005", ids)

        # 4. Session-level SET lock_timeout persists across and after transactions
        sql_sess = (FIXTURES_DIR / "mig_04_session_timeout_multi_tx.sql").read_text(encoding="utf-8")
        res_sess = check_migration_safety.analyze_migration_sql(sql_sess, pg_version=16)
        self.assertValidSchema(res_sess)
        self.assertEqual(res_sess["status"], "ok")
        self.assertEqual(res_sess["metrics"]["risk_classification"], "LOW")

    def test_regression_05_06_07_concurrent_index_and_multiple_transactions(self):
        # 5. CREATE INDEX CONCURRENTLY inside BEGIN..COMMIT -> CRITICAL
        sql_in_tx = (FIXTURES_DIR / "mig_05_concurrent_inside_tx.sql").read_text(encoding="utf-8")
        res_in_tx = check_migration_safety.analyze_migration_sql(sql_in_tx, pg_version=16)
        self.assertValidSchema(res_in_tx)
        self.assertEqual(res_in_tx["status"], "critical")
        self.assertEqual(res_in_tx["metrics"]["risk_classification"], "CRITICAL")
        self.assertIn("MIG-TXN-003", {f["id"] for f in res_in_tx["findings"]})

        # 6. CREATE INDEX CONCURRENTLY after COMMIT -> LOW / ok (NOT inside a transaction!)
        sql_after_commit = (FIXTURES_DIR / "mig_06_concurrent_after_commit.sql").read_text(encoding="utf-8")
        res_after_commit = check_migration_safety.analyze_migration_sql(sql_after_commit, pg_version=16)
        self.assertValidSchema(res_after_commit)
        self.assertEqual(res_after_commit["status"], "ok")
        self.assertEqual(res_after_commit["metrics"]["risk_classification"], "LOW")
        self.assertFalse(any(f["category"] == "transaction_hazard" for f in res_after_commit["findings"]))

        # 7. Multiple transactions with local lock_timeout -> LOW / ok
        sql_multi = (FIXTURES_DIR / "mig_07_multiple_transactions.sql").read_text(encoding="utf-8")
        res_multi = check_migration_safety.analyze_migration_sql(sql_multi, pg_version=16)
        self.assertValidSchema(res_multi)
        self.assertEqual(res_multi["status"], "ok")
        self.assertEqual(res_multi["metrics"]["transactions_committed"], 2)

    def test_regression_08_09_10_rollback_invalid_tx_and_mixed_statements(self):
        # 8. ROLLBACK discards validated check constraint so subsequent SET NOT NULL is flagged as unsafe scan
        sql_rb = (FIXTURES_DIR / "mig_08_rollback_behavior.sql").read_text(encoding="utf-8")
        res_rb = check_migration_safety.analyze_migration_sql(sql_rb, pg_version=16)
        self.assertValidSchema(res_rb)
        self.assertEqual(res_rb["status"], "warning")
        rb_ids = {f["id"] for f in res_rb["findings"]}
        self.assertIn("MIG-TXN-ROLLBACK-005", rb_ids)
        self.assertIn("MIG-NOTNULL-006", rb_ids)

        # 9. Invalid transaction sequences (orphan COMMIT, SET LOCAL outside tx, nested BEGIN, unclosed BEGIN)
        sql_inv = (FIXTURES_DIR / "mig_09_invalid_tx_sequences.sql").read_text(encoding="utf-8")
        res_inv = check_migration_safety.analyze_migration_sql(sql_inv, pg_version=16)
        self.assertValidSchema(res_inv)
        inv_ids = {f["id"] for f in res_inv["findings"]}
        self.assertIn("MIG-TXN-ORPHAN-001", inv_ids)
        self.assertIn("MIG-TIMEOUT-LOCAL-NOTX-002", inv_ids)
        self.assertIn("MIG-TXN-NESTED-004", inv_ids)
        self.assertIn("MIG-TXN-UNCLOSED", inv_ids)

        # 10. Mixed safe (statement 2) and unsafe (statement 3 blocking index)
        sql_mix = (FIXTURES_DIR / "mig_10_mixed_safe_and_unsafe.sql").read_text(encoding="utf-8")
        res_mix = check_migration_safety.analyze_migration_sql(sql_mix, pg_version=16)
        self.assertValidSchema(res_mix)
        self.assertEqual(res_mix["status"], "warning")
        self.assertEqual(res_mix["metrics"]["risk_classification"], "HIGH")
        mix_ids = {f["id"] for f in res_mix["findings"]}
        self.assertIn("MIG-IDX-003", mix_ids)
        self.assertNotIn("MIG-TIMEOUT-002", mix_ids)


    def test_streaming_bounded_subprocess_large_stdout_and_process_termination(self):
        import os as _os
        res = run_bounded_command(
            [sys.executable, "-c", "import time\nwhile True:\n    print('X' * 4096, flush=True)"],
            timeout_sec=5.0,
            max_bytes=8192,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["truncated"])
        self.assertTrue(res["stdout_truncated"])
        self.assertEqual(res["terminated_reason"], "output_limit_exceeded")
        self.assertLessEqual(len(res["stdout"].encode("utf-8")), 8192)
        self.assertIsNotNone(res["child_pid"])
        with self.assertRaises(ProcessLookupError):
            _os.kill(res["child_pid"], 0)

    def test_streaming_bounded_subprocess_large_stderr_and_simultaneous_io(self):
        res_err = run_bounded_command(
            [sys.executable, "-c", "import sys\nfor _ in range(500):\n    sys.stderr.write('E' * 512)\n    sys.stderr.flush()"],
            timeout_sec=5.0,
            max_bytes=4096,
        )
        self.assertTrue(res_err["truncated"])
        self.assertTrue(res_err["stderr_truncated"])
        self.assertLessEqual(len(res_err["stderr"].encode("utf-8")), 4096)

        res_both = run_bounded_command(
            [sys.executable, "-c", "import sys\nfor _ in range(100):\n    sys.stdout.write('O' * 200)\n    sys.stderr.write('E' * 200)\n    sys.stdout.flush()\n    sys.stderr.flush()"],
            timeout_sec=5.0,
            max_bytes=4096,
        )
        self.assertTrue(res_both["truncated"])
        self.assertLessEqual(len(res_both["stdout"].encode("utf-8")), 4096)
        self.assertLessEqual(len(res_both["stderr"].encode("utf-8")), 4096)

    def test_streaming_bounded_subprocess_timeout_missing_exec_and_unsafe_args(self):
        import os as _os
        res_to = run_bounded_command(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout_sec=0.25,
            max_bytes=4096,
        )
        self.assertFalse(res_to["ok"])
        self.assertTrue(res_to["timed_out"])
        self.assertTrue(res_to["truncated"])
        self.assertEqual(res_to["terminated_reason"], "timeout")
        with self.assertRaises(ProcessLookupError):
            _os.kill(res_to["child_pid"], 0)

        res_missing = run_bounded_command(["/nonexistent_binary_xyz_12345"])
        self.assertFalse(res_missing["ok"])
        self.assertEqual(res_missing["returncode"], 127)
        self.assertEqual(res_missing["terminated_reason"], "executable_not_found")

        res_unsafe = run_bounded_command(["python3", "arg_with_\x00_null"])
        self.assertFalse(res_unsafe["ok"])
        self.assertEqual(res_unsafe["terminated_reason"], "invalid_arguments")

        for priv_bin in ("sudo", "su", "pkexec"):
            res_priv = run_bounded_command([priv_bin, "id"])
            self.assertFalse(res_priv["ok"])
            self.assertEqual(res_priv["terminated_reason"], "blocked_privilege_escalation")



    def test_bug4_rollback_restores_pre_transaction_session_lock_timeout(self):
        # Case 1: Session lock_timeout is '0' before BEGIN, set to '5s' inside BEGIN, then ROLLBACK -> restores '0' (unprotected!)
        sql_rb_unprotected = """
        SET lock_timeout = '0';
        BEGIN;
        SET lock_timeout = '5s';
        ROLLBACK;
        ALTER TABLE users ADD COLUMN status TEXT;
        """
        res1 = check_migration_safety.analyze_migration_sql(sql_rb_unprotected, pg_version=16)
        self.assertValidSchema(res1)
        ids1 = {f["id"]: f for f in res1["findings"]}
        self.assertIn("MIG-TIMEOUT-005", ids1, "Statement 5 after ROLLBACK must be flagged as lacking active lock_timeout")
        self.assertIsNone(ids1["MIG-TIMEOUT-005"]["evidence"]["effective_lock_timeout"])

        # Case 2 (Reverse): Session lock_timeout is '5s' before BEGIN, set to '0' inside BEGIN, then ROLLBACK -> restores '5s' (protected!)
        sql_rb_restored = """
        SET lock_timeout = '5s';
        BEGIN;
        SET lock_timeout = '0';
        ROLLBACK;
        ALTER TABLE users ADD COLUMN status TEXT;
        """
        res2 = check_migration_safety.analyze_migration_sql(sql_rb_restored, pg_version=16)
        self.assertValidSchema(res2)
        ids2 = {f["id"] for f in res2["findings"]}
        self.assertNotIn("MIG-TIMEOUT-005", ids2, "Statement 5 after ROLLBACK must inherit restored 5s session lock_timeout")

        # Case 3: Session lock_timeout set to '5s' inside BEGIN..COMMIT persists after COMMIT
        sql_commit_persists = """
        SET lock_timeout = '0';
        BEGIN;
        SET lock_timeout = '5s';
        COMMIT;
        ALTER TABLE users ADD COLUMN status TEXT;
        """
        res3 = check_migration_safety.analyze_migration_sql(sql_commit_persists, pg_version=16)
        self.assertValidSchema(res3)
        ids3 = {f["id"] for f in res3["findings"]}
        self.assertNotIn("MIG-TIMEOUT-005", ids3)

    @staticmethod
    def _cleanup_subprocess_test_processes(res, grandchild_pid, marker_path):
        import os as _os
        import signal as _signal
        from common import _reap_process_group

        if grandchild_pid is None and marker_path is not None and marker_path.exists():
            try:
                raw_pid = marker_path.read_text(encoding="utf-8").strip()
                if raw_pid.isdigit():
                    grandchild_pid = int(raw_pid)
            except Exception:
                pass

        if grandchild_pid is None and isinstance(res, dict):
            stdout_txt = res.get("stdout") or ""
            for line in stdout_txt.splitlines():
                if line.startswith("GRANDCHILD_PID="):
                    val = line.split("=", 1)[1].strip()
                    if val.isdigit():
                        grandchild_pid = int(val)
                        break

        child_pid = res.get("child_pid") if isinstance(res, dict) else None
        if child_pid:
            for sig in (_signal.SIGKILL,):
                try:
                    _os.killpg(child_pid, sig)
                except Exception:
                    pass
                try:
                    _os.kill(child_pid, sig)
                except Exception:
                    pass
            try:
                _reap_process_group(child_pid)
            except Exception:
                pass

        if grandchild_pid:
            try:
                _os.killpg(grandchild_pid, _signal.SIGKILL)
            except Exception:
                pass
            try:
                _os.kill(grandchild_pid, _signal.SIGKILL)
            except Exception:
                pass
            try:
                _os.waitpid(grandchild_pid, _os.WNOHANG)
            except Exception:
                pass

    def test_bug1_descendant_ignoring_sigterm_killed_on_output_limit(self):
        import os as _os
        import tempfile as _tempfile
        from common import is_pid_alive

        with _tempfile.TemporaryDirectory() as tmpdir:
            marker_path = Path(tmpdir) / "grandchild_limit.pid"
            script = (
                "import os, signal, subprocess, sys, time\n"
                "marker_str = sys.argv[1]\n"
                "tmp_str = marker_str + '.tmp'\n"
                "if hasattr(os, 'fork'):\n"
                "    r_fd, w_fd = os.pipe()\n"
                "    pid = os.fork()\n"
                "    if pid == 0:\n"
                "        os.close(r_fd)\n"
                "        signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "        os.write(w_fd, b'READY\\n')\n"
                "        os.close(w_fd)\n"
                "        while True:\n"
                "            time.sleep(1.0)\n"
                "    os.close(w_fd)\n"
                "    os.read(r_fd, 16)\n"
                "    os.close(r_fd)\n"
                "    gpid = pid\n"
                "else:\n"
                "    child = subprocess.Popen([sys.executable, '-c', "
                "'import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); sys.stdout.write(\"READY\\n\"); sys.stdout.flush(); time.sleep(60)'], "
                "stdout=subprocess.PIPE, text=True)\n"
                "    child.stdout.readline()\n"
                "    gpid = child.pid\n"
                "with open(tmp_str, 'w', encoding='utf-8') as f:\n"
                "    f.write(f'{gpid}\\n')\n"
                "    f.flush()\n"
                "os.replace(tmp_str, marker_str)\n"
                "sys.stdout.write(f'GRANDCHILD_PID={gpid}\\n')\n"
                "sys.stdout.flush()\n"
                "chunk = 'Z' * 4096\n"
                "while True:\n"
                "    sys.stdout.write(chunk)\n"
                "    sys.stdout.flush()\n"
                "    time.sleep(0.01)\n"
            )
            res = None
            grandchild_pid = None
            try:
                res = run_bounded_command(
                    [sys.executable, "-c", script, str(marker_path)],
                    timeout_sec=5.0,
                    max_bytes=4096,
                    ready_file=marker_path,
                )
                if marker_path.exists():
                    grandchild_pid = int(marker_path.read_text(encoding="utf-8").strip())
                self.assertTrue(marker_path.exists(), "Deterministic startup marker file was not written")
                self.assertIsNotNone(grandchild_pid)
                self.assertGreater(grandchild_pid, 0)
                self.assertTrue(res["truncated"])
                self.assertTrue(res["stdout_truncated"])
                self.assertEqual(res["terminated_reason"], "output_limit_exceeded")
                self.assertIn(f"GRANDCHILD_PID={grandchild_pid}", res["stdout"])
                self.assertFalse(is_pid_alive(res["child_pid"]))
                self.assertFalse(is_pid_alive(grandchild_pid))
                with self.assertRaises(ProcessLookupError):
                    _os.kill(grandchild_pid, 0)
            finally:
                self._cleanup_subprocess_test_processes(res, grandchild_pid, marker_path)

    def test_bug1_descendant_ignoring_sigterm_killed_on_timeout(self):
        import os as _os
        import tempfile as _tempfile
        from common import is_pid_alive

        with _tempfile.TemporaryDirectory() as tmpdir:
            marker_path = Path(tmpdir) / "grandchild_timeout.pid"
            script = (
                "import os, signal, subprocess, sys, time\n"
                "marker_str = sys.argv[1]\n"
                "tmp_str = marker_str + '.tmp'\n"
                "if hasattr(os, 'fork'):\n"
                "    r_fd, w_fd = os.pipe()\n"
                "    pid = os.fork()\n"
                "    if pid == 0:\n"
                "        os.close(r_fd)\n"
                "        signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "        os.write(w_fd, b'READY\\n')\n"
                "        os.close(w_fd)\n"
                "        while True:\n"
                "            time.sleep(1.0)\n"
                "    os.close(w_fd)\n"
                "    os.read(r_fd, 16)\n"
                "    os.close(r_fd)\n"
                "    gpid = pid\n"
                "else:\n"
                "    child = subprocess.Popen([sys.executable, '-c', "
                "'import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); sys.stdout.write(\"READY\\n\"); sys.stdout.flush(); time.sleep(60)'], "
                "stdout=subprocess.PIPE, text=True)\n"
                "    child.stdout.readline()\n"
                "    gpid = child.pid\n"
                "with open(tmp_str, 'w', encoding='utf-8') as f:\n"
                "    f.write(f'{gpid}\\n')\n"
                "    f.flush()\n"
                "os.replace(tmp_str, marker_str)\n"
                "sys.stdout.write(f'GRANDCHILD_PID={gpid}\\n')\n"
                "sys.stdout.flush()\n"
                "time.sleep(60.0)\n"
            )
            res = None
            grandchild_pid = None
            try:
                res = run_bounded_command(
                    [sys.executable, "-c", script, str(marker_path)],
                    timeout_sec=0.4,
                    max_bytes=4096,
                    ready_file=marker_path,
                    startup_timeout_sec=10.0,
                )
                if marker_path.exists():
                    grandchild_pid = int(marker_path.read_text(encoding="utf-8").strip())
                self.assertTrue(marker_path.exists(), "Descendant did not complete readiness handshake before timeout")
                self.assertIsNotNone(grandchild_pid)
                self.assertGreater(grandchild_pid, 0)
                self.assertFalse(res["ok"])
                self.assertTrue(res["timed_out"])
                self.assertTrue(res["truncated"])
                self.assertEqual(res["terminated_reason"], "timeout")
                self.assertIn(f"GRANDCHILD_PID={grandchild_pid}", res["stdout"])
                self.assertFalse(is_pid_alive(res["child_pid"]))
                self.assertFalse(is_pid_alive(grandchild_pid))
                with self.assertRaises(ProcessLookupError):
                    _os.kill(grandchild_pid, 0)
            finally:
                self._cleanup_subprocess_test_processes(res, grandchild_pid, marker_path)

    def test_bug1_parent_exits_on_sigterm_while_descendant_ignores_sigterm(self):
        import os as _os
        import tempfile as _tempfile
        from common import is_pid_alive

        with _tempfile.TemporaryDirectory() as tmpdir:
            marker_path = Path(tmpdir) / "grandchild_parent_exit.pid"
            script = (
                "import os, signal, sys, time\n"
                "marker_str = sys.argv[1]\n"
                "tmp_str = marker_str + '.tmp'\n"
                "signal.signal(signal.SIGTERM, lambda s, f: os._exit(0))\n"
                "r_fd, w_fd = os.pipe()\n"
                "pid = os.fork()\n"
                "if pid == 0:\n"
                "    os.close(r_fd)\n"
                "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "    os.write(w_fd, b'READY\\n')\n"
                "    os.close(w_fd)\n"
                "    while True:\n"
                "        time.sleep(1.0)\n"
                "os.close(w_fd)\n"
                "os.read(r_fd, 16)\n"
                "os.close(r_fd)\n"
                "with open(tmp_str, 'w', encoding='utf-8') as f:\n"
                "    f.write(f'{pid}\\n')\n"
                "    f.flush()\n"
                "os.replace(tmp_str, marker_str)\n"
                "sys.stdout.write(f'GRANDCHILD_PID={pid}\\n')\n"
                "sys.stdout.flush()\n"
                "time.sleep(60.0)\n"
            )
            res = None
            grandchild_pid = None
            try:
                res = run_bounded_command(
                    [sys.executable, "-c", script, str(marker_path)],
                    timeout_sec=0.4,
                    max_bytes=4096,
                    ready_file=marker_path,
                    startup_timeout_sec=10.0,
                )
                if marker_path.exists():
                    grandchild_pid = int(marker_path.read_text(encoding="utf-8").strip())
                self.assertTrue(marker_path.exists(), "Descendant did not complete readiness handshake before timeout")
                self.assertIsNotNone(grandchild_pid)
                self.assertGreater(grandchild_pid, 0)
                self.assertTrue(res["timed_out"])
                self.assertEqual(res["terminated_reason"], "timeout")
                self.assertIn(f"GRANDCHILD_PID={grandchild_pid}", res["stdout"])
                self.assertFalse(is_pid_alive(res["child_pid"]))
                self.assertFalse(is_pid_alive(grandchild_pid))
                with self.assertRaises(ProcessLookupError):
                    _os.kill(grandchild_pid, 0)
            finally:
                self._cleanup_subprocess_test_processes(res, grandchild_pid, marker_path)



    def test_reset_lock_timeout_savepoint_rollback_and_vacuum_full_lock_table_hazards(self):
        # 1. RESET lock_timeout clears prior session lock_timeout so subsequent DDL is flagged
        sql_reset = """
        SET lock_timeout = '5s';
        RESET lock_timeout;
        ALTER TABLE users ADD COLUMN bio TEXT;
        """
        res_reset = check_migration_safety.analyze_migration_sql(sql_reset, pg_version=16)
        self.assertValidSchema(res_reset)
        self.assertEqual(res_reset["status"], "warning")
        self.assertIn("MIG-TIMEOUT-003", {f["id"] for f in res_reset["findings"]})

        # 2. RESET ALL clears BOTH lock_timeout and statement_timeout (standalone, COMMIT, and ROLLBACK)
        sql_reset_all_stmt = """
        SET lock_timeout = '5s';
        SET statement_timeout = '30s';
        RESET ALL;
        SELECT 1;
        """
        res_ra_stmt = check_migration_safety.analyze_migration_sql(sql_reset_all_stmt, pg_version=16)
        self.assertValidSchema(res_ra_stmt)
        tl_select = res_ra_stmt["metrics"]["statement_timeline"][-1]
        self.assertIsNone(tl_select["effective_lock_timeout"])
        self.assertIsNone(tl_select["effective_statement_timeout"])

        # RESET ALL inside BEGIN..COMMIT persists after COMMIT
        sql_ra_commit = """
        SET lock_timeout = '5s';
        SET statement_timeout = '30s';
        BEGIN;
        RESET ALL;
        COMMIT;
        ALTER TABLE users ADD COLUMN bio TEXT;
        """
        res_ra_commit = check_migration_safety.analyze_migration_sql(sql_ra_commit, pg_version=16)
        self.assertValidSchema(res_ra_commit)
        self.assertIn("MIG-TIMEOUT-006", {f["id"] for f in res_ra_commit["findings"]})
        tl_commit_ddl = res_ra_commit["metrics"]["statement_timeline"][-1]
        self.assertIsNone(tl_commit_ddl["effective_lock_timeout"])
        self.assertIsNone(tl_commit_ddl["effective_statement_timeout"])

        # RESET ALL inside BEGIN..ROLLBACK is undone by ROLLBACK, restoring pre-transaction lock_timeout & statement_timeout
        sql_ra_rollback = """
        SET lock_timeout = '5s';
        SET statement_timeout = '30s';
        BEGIN;
        RESET ALL;
        ROLLBACK;
        ALTER TABLE users ADD COLUMN bio TEXT;
        """
        res_ra_rb = check_migration_safety.analyze_migration_sql(sql_ra_rollback, pg_version=16)
        self.assertValidSchema(res_ra_rb)
        self.assertNotIn("MIG-TIMEOUT-006", {f["id"] for f in res_ra_rb["findings"]})
        tl_rb_ddl = res_ra_rb["metrics"]["statement_timeline"][-1]
        self.assertEqual(tl_rb_ddl["effective_lock_timeout"], "'5s'")
        self.assertEqual(tl_rb_ddl["effective_statement_timeout"], "'30s'")

        # 3a. Savepoint rollback restores active timeout that existed at SAVEPOINT s1
        sql_sp_restore_active = """
        BEGIN;
        SET LOCAL lock_timeout = '5s';
        SAVEPOINT s1;
        SET LOCAL lock_timeout = '0';
        ROLLBACK TO SAVEPOINT s1;
        ALTER TABLE users ADD COLUMN status TEXT;
        COMMIT;
        """
        res_sp_active = check_migration_safety.analyze_migration_sql(sql_sp_restore_active, pg_version=16)
        self.assertValidSchema(res_sp_active)
        self.assertEqual(res_sp_active["status"], "ok")
        self.assertNotIn("MIG-TIMEOUT-006", {f["id"] for f in res_sp_active["findings"]})
        self.assertEqual(res_sp_active["metrics"]["statement_timeline"][5]["effective_lock_timeout"], "'5s'")

        # 3b. Savepoint rollback undoes timeout set AFTER SAVEPOINT s1 (restoring unprotected state)
        sql_sp_undo_later = """
        BEGIN;
        SAVEPOINT s1;
        SET LOCAL lock_timeout = '5s';
        ROLLBACK TO SAVEPOINT s1;
        ALTER TABLE users ADD COLUMN bio TEXT;
        COMMIT;
        """
        res_sp_undo = check_migration_safety.analyze_migration_sql(sql_sp_undo_later, pg_version=16)
        self.assertValidSchema(res_sp_undo)
        self.assertEqual(res_sp_undo["status"], "warning")
        self.assertIn("MIG-TIMEOUT-005", {f["id"] for f in res_sp_undo["findings"]})

        # 3c. Rolling back to an earlier savepoint s1 discards later savepoint s2
        sql_sp_nested_discard = """
        BEGIN;
        SET LOCAL lock_timeout = '5s';
        SAVEPOINT s1;
        SET LOCAL lock_timeout = '2s';
        SAVEPOINT s2;
        SET LOCAL lock_timeout = '0';
        ROLLBACK TO SAVEPOINT s1;
        ROLLBACK TO SAVEPOINT s2;
        COMMIT;
        """
        res_sp_nested = check_migration_safety.analyze_migration_sql(sql_sp_nested_discard, pg_version=16)
        self.assertValidSchema(res_sp_nested)
        self.assertIn("MIG-TXN-SAVEPOINT-UNKNOWN-008", {f["id"] for f in res_sp_nested["findings"]})

        # 4. VACUUM FULL, LOCK TABLE, and non-concurrent REFRESH MATERIALIZED VIEW are flagged
        sql_heavy = """
        SET lock_timeout = '2s';
        VACUUM FULL users;
        LOCK TABLE orders IN ACCESS EXCLUSIVE MODE;
        REFRESH MATERIALIZED VIEW sales_summary_mv;
        """
        res_heavy = check_migration_safety.analyze_migration_sql(sql_heavy, pg_version=16)
        self.assertValidSchema(res_heavy)
        self.assertEqual(res_heavy["status"], "critical")
        heavy_ids = {f["id"] for f in res_heavy["findings"]}
        self.assertIn("MIG-REWRITE-002", heavy_ids)
        self.assertIn("MIG-LOCK-003", heavy_ids)
        self.assertIn("MIG-LOCK-004", heavy_ids)

        # 5. generate_migration_report supports text EXPLAIN plan files
        rep_txt = generate_migration_report.generate_full_report(
            FIXTURES_DIR / "mig_01_timeout_before_ddl.sql",
            EXAMPLES_DIR / "slow_queries.sql",
            FIXTURES_DIR / "text_explain_plan.txt",
            EXAMPLES_DIR / "schema.sql",
            pg_version=16,
        )
        self.assertValidSchema(rep_txt)

if __name__ == "__main__":
    unittest.main()
