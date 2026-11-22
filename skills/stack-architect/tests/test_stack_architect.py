import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))
import cost_estimator
import generate_architecture
import infrastructure_sizer
import requirements_validator
import scaffold_infrastructure
import stack_selector
import validate_blueprint
import workload_calculator
from common import resolve_safe_child_path, run_bounded_command, validate_against_schema


class TestStackArchitect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.req_schema = json.loads((SCHEMAS_DIR / "requirements.schema.json").read_text(encoding="utf-8"))
        cls.size_schema = json.loads((SCHEMAS_DIR / "sizing.schema.json").read_text(encoding="utf-8"))
        cls.price_schema = json.loads((SCHEMAS_DIR / "pricing.schema.json").read_text(encoding="utf-8"))
        cls.arch_schema = json.loads((SCHEMAS_DIR / "architecture.schema.json").read_text(encoding="utf-8"))
        cls.scaf_schema = json.loads((SCHEMAS_DIR / "scaffold.schema.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.saas = json.loads((EXAMPLES_DIR / "saas_constraints.json").read_text(encoding="utf-8"))
        self.high_scale = json.loads((EXAMPLES_DIR / "high_scale_constraints.json").read_text(encoding="utf-8"))

    def test_requirements_validator_schema_and_unknown_assumptions(self):
        res = requirements_validator.validate_requirements(self.saas)
        self.assertEqual(validate_against_schema(res, self.req_schema), [])
        self.assertEqual(res["status"], "ok")
        assumptions = res["metrics"]["assumptions_register"]
        self.assertEqual(len(assumptions), 18)
        defaulted = [a for a in assumptions if a["source"] == "default_assumption"]
        self.assertEqual(len(defaulted), 2)

    def test_boundary_and_invalid_constraints_rejected(self):
        bad = dict(self.saas, expected_rps=-10, monthly_budget_usd=0)
        res = requirements_validator.validate_requirements(bad)
        self.assertEqual(res["status"], "error")
        self.assertTrue(len(res["errors"]) >= 2)

    def test_workload_calculator_sensitivity(self):
        res = workload_calculator.calculate_workload(self.saas)
        self.assertEqual(res["status"], "ok")
        b1 = res["metrics"]["baseline_1x"]
        b2 = res["metrics"]["sensitivity_2x_growth"]
        b5 = res["metrics"]["sensitivity_5x_surge"]
        self.assertEqual(b1["peak_rps"], 450.0)
        self.assertEqual(b2["peak_rps"], 900.0)
        self.assertEqual(b5["peak_rps"], 2250.0)

    def test_infrastructure_sizer_schema_and_scaling(self):
        s_small_full = infrastructure_sizer.size_infrastructure(self.saas)
        s_large_full = infrastructure_sizer.size_infrastructure(self.high_scale)
        self.assertEqual(validate_against_schema(s_small_full, self.size_schema), [])
        self.assertEqual(validate_against_schema(s_large_full, self.size_schema), [])
        s_small = s_small_full["metrics"]
        s_large = s_large_full["metrics"]
        self.assertGreater(s_large["application_tier"]["recommended_vcpus"], s_small["application_tier"]["recommended_vcpus"])
        self.assertGreater(s_large["database_tier"]["recommended_ram_gib"], s_small["database_tier"]["recommended_ram_gib"])
        self.assertEqual(s_large["application_tier"]["ha_instances"], 2)

    def test_cost_estimator_pricing_schema_and_provenance(self):
        res = cost_estimator.estimate_costs(self.saas, custom_pricing=[{
            "provider": "CustomVPS",
            "region": "ap-south-1",
            "service": "KVM NVMe VPS",
            "instance_type": "kvm-4c-16g",
            "resource_specifications": "4 vCPU, 16 GB RAM, 160 GB NVMe",
            "currency": "USD",
            "billing_unit": "per month",
            "price": 28.0,
            "source_url": "https://example.com/custom-rate-card",
            "verification_timestamp": "2026-11-17T00:00:00Z",
        }])
        self.assertEqual(validate_against_schema(res, self.price_schema), [])
        self.assertEqual(res["status"], "ok")
        provenance_types = {r["provenance_type"] for r in res["metrics"]["verified_pricing_records"]}
        self.assertIn("verified_current_price", provenance_types)
        self.assertIn("user_supplied_assumption", provenance_types)

    def test_stack_selector_has_all_13_layers_and_7_justifications(self):
        res = stack_selector.select_stack(self.saas)
        decisions = res["metrics"]["stack_decisions"]
        expected_layers = {
            "runtime", "backend_framework", "frontend_framework", "database", "cache",
            "queue", "authentication", "object_storage", "api_architecture",
            "observability", "deployment", "reverse_proxy", "ci_cd"
        }
        self.assertEqual(set(decisions.keys()), expected_layers)
        for layer, info in decisions.items():
            for field in ("choice", "why_selected", "alternatives_considered", "why_rejected", "operational_complexity", "cost_implications", "scaling_limitations", "migration_path"):
                self.assertIn(field, info, f"Missing {field} in {layer}")

    def test_architecture_blueprint_schema(self):
        bp = generate_architecture.build_architecture_blueprint(self.saas)
        self.assertEqual(validate_against_schema(bp, self.arch_schema), [])

    def test_scaffold_dry_run_overwrite_protection_and_path_traversal_guard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with self.assertRaises(ValueError):
                resolve_safe_child_path(base, "../escaped.txt")
            with self.assertRaises(ValueError):
                resolve_safe_child_path(base, "/outside-base/escaped.txt")

            dry_target = base / "dry-run-app"
            scaf_dry = scaffold_infrastructure.scaffold_project(self.saas, dry_target, force=False, dry_run=True)
            self.assertEqual(validate_against_schema(scaf_dry, self.scaf_schema), [])
            self.assertTrue(scaf_dry["metrics"]["dry_run"])
            self.assertFalse(dry_target.exists(), "Dry-run must not create directory on disk")

            target = base / "day0-app"
            scaf = scaffold_infrastructure.scaffold_project(self.saas, target, force=False, dry_run=False)
            self.assertEqual(validate_against_schema(scaf, self.scaf_schema), [])
            self.assertEqual(scaf["status"], "ok")

            val = validate_blueprint.validate_scaffold(target)
            self.assertEqual(val["status"], "ok")
            self.assertTrue(val["metrics"]["compose_validation"]["valid"])

            scaf_overwrite = scaffold_infrastructure.scaffold_project(self.saas, target, force=False, dry_run=False)
            self.assertEqual(scaf_overwrite["status"], "error")


    def test_runtime_matched_scaffolding_for_go_rust_nodejs_python_and_conditional_redis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # 1. Go + in_process cache (expected_rps=150, budget=120, team_experience="go_postgres") -> Go Dockerfile, NO Redis
            c_go = dict(self.saas, team_experience="go_postgres", expected_rps=150, monthly_budget_usd=120.0)
            go_dir = base / "scaf-go"
            res_go = scaffold_infrastructure.scaffold_project(c_go, go_dir)
            self.assertEqual(res_go["status"], "ok")
            self.assertEqual(res_go["metrics"]["selected_architecture_config"]["backend_runtime"], "go")
            self.assertFalse(res_go["metrics"]["selected_architecture_config"]["redis_enabled"])
            self.assertTrue((go_dir / "go.mod").exists())
            self.assertTrue((go_dir / "cmd/server/main.go").exists())
            self.assertIn("FROM golang:", (go_dir / "Dockerfile").read_text(encoding="utf-8"))
            self.assertNotIn("  redis:", (go_dir / "docker-compose.yml").read_text(encoding="utf-8"))
            self.assertFalse((go_dir / "config/redis.conf").exists())
            self.assertEqual(validate_blueprint.validate_scaffold(go_dir)["status"], "ok")

            # 2. Rust + Redis enabled (expected_rps=600, budget=500, team_experience="rust_postgres") -> Rust Dockerfile, WITH Redis
            c_rs = dict(self.saas, team_experience="rust_postgres", expected_rps=600, monthly_budget_usd=500.0)
            rs_dir = base / "scaf-rust"
            res_rs = scaffold_infrastructure.scaffold_project(c_rs, rs_dir)
            self.assertEqual(res_rs["status"], "ok")
            self.assertEqual(res_rs["metrics"]["selected_architecture_config"]["backend_runtime"], "rust")
            self.assertTrue(res_rs["metrics"]["selected_architecture_config"]["redis_enabled"])
            self.assertTrue((rs_dir / "Cargo.toml").exists())
            self.assertTrue((rs_dir / "src/main.rs").exists())
            self.assertIn("FROM rust:", (rs_dir / "Dockerfile").read_text(encoding="utf-8"))
            self.assertIn("  redis:", (rs_dir / "docker-compose.yml").read_text(encoding="utf-8"))
            self.assertTrue((rs_dir / "config/redis.conf").exists())
            self.assertEqual(validate_blueprint.validate_scaffold(rs_dir)["status"], "ok")

            # 3. Node.js + in_process cache -> Node.js Dockerfile, NO Redis
            c_node = dict(self.saas, team_experience="nodejs_typescript_postgres", expected_rps=100, monthly_budget_usd=100.0)
            node_dir = base / "scaf-node"
            res_node = scaffold_infrastructure.scaffold_project(c_node, node_dir)
            self.assertEqual(res_node["metrics"]["selected_architecture_config"]["backend_runtime"], "nodejs")
            self.assertFalse(res_node["metrics"]["selected_architecture_config"]["redis_enabled"])
            self.assertTrue((node_dir / "package.json").exists())
            self.assertTrue((node_dir / "src/server.js").exists())
            self.assertIn("FROM node:", (node_dir / "Dockerfile").read_text(encoding="utf-8"))
            self.assertNotIn("  redis:", (node_dir / "docker-compose.yml").read_text(encoding="utf-8"))
            self.assertEqual(validate_blueprint.validate_scaffold(node_dir)["status"], "ok")

            # 4. Python + Redis enabled -> Python Dockerfile, WITH Redis
            c_py = dict(self.saas, team_experience="python_fastapi_postgres_redis", expected_rps=150, monthly_budget_usd=150.0)
            py_dir = base / "scaf-python"
            res_py = scaffold_infrastructure.scaffold_project(c_py, py_dir)
            self.assertEqual(res_py["metrics"]["selected_architecture_config"]["backend_runtime"], "python")
            self.assertTrue(res_py["metrics"]["selected_architecture_config"]["redis_enabled"])
            self.assertTrue((py_dir / "requirements.txt").exists())
            self.assertTrue((py_dir / "src/healthcheck_server.py").exists())
            self.assertIn("FROM python:", (py_dir / "Dockerfile").read_text(encoding="utf-8"))
            self.assertIn("  redis:", (py_dir / "docker-compose.yml").read_text(encoding="utf-8"))
            self.assertEqual(validate_blueprint.validate_scaffold(py_dir)["status"], "ok")

    def test_hetzner_ax42_revalidated_pricing_regression(self):
        res = cost_estimator.estimate_costs(self.saas)
        catalog = {r["id"]: r for r in res["metrics"]["verified_pricing_records"]}
        self.assertIn("hetzner-dedicated-ax42-1-standard", catalog)
        ax42 = catalog["hetzner-dedicated-ax42-1-standard"]
        self.assertEqual(ax42["offering_type"], "standard")
        self.assertEqual(ax42["currency"], "EUR")
        self.assertEqual(ax42["price"], 97.30)
        self.assertEqual(ax42["setup_fee"], 49.00)
        self.assertEqual(ax42["ipv4_monthly_fee"], 1.70)
        self.assertFalse(ax42["vat_included"])
        self.assertIn("hetzner.com/dedicated-rootserver/ax42/configurator", ax42["source_url"])
        # Ensure old €46.00 figure does not exist
        for rec in res["metrics"]["verified_pricing_records"]:
            self.assertNotEqual(rec.get("price"), 46.0)


    def test_streaming_bounded_subprocess_large_stdout_and_process_termination(self):
        import os as _os
        res = run_bounded_command(
            [sys.executable, "-c", "import time\nwhile True:\n    print('X' * 4096, flush=True)"],
            timeout_sec=5.0,
            max_bytes=8192,
            allowed_executables={_os.path.basename(sys.executable)},
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
        import os as _os
        py_allow = {_os.path.basename(sys.executable)}
        res_err = run_bounded_command(
            [sys.executable, "-c", "import sys\nfor _ in range(500):\n    sys.stderr.write('E' * 512)\n    sys.stderr.flush()"],
            timeout_sec=5.0,
            max_bytes=4096,
            allowed_executables=py_allow,
        )
        self.assertTrue(res_err["truncated"])
        self.assertTrue(res_err["stderr_truncated"])
        self.assertLessEqual(len(res_err["stderr"].encode("utf-8")), 4096)

        res_both = run_bounded_command(
            [sys.executable, "-c", "import sys\nfor _ in range(100):\n    sys.stdout.write('O' * 200)\n    sys.stderr.write('E' * 200)\n    sys.stdout.flush()\n    sys.stderr.flush()"],
            timeout_sec=5.0,
            max_bytes=4096,
            allowed_executables=py_allow,
        )
        self.assertTrue(res_both["truncated"])
        self.assertLessEqual(len(res_both["stdout"].encode("utf-8")), 4096)
        self.assertLessEqual(len(res_both["stderr"].encode("utf-8")), 4096)

    def test_streaming_bounded_subprocess_timeout_missing_exec_and_unsafe_args(self):
        import os as _os
        py_allow = {_os.path.basename(sys.executable)}
        res_to = run_bounded_command(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout_sec=0.25,
            max_bytes=4096,
            allowed_executables=py_allow,
        )
        self.assertFalse(res_to["ok"])
        self.assertTrue(res_to["timed_out"])
        self.assertTrue(res_to["truncated"])
        self.assertEqual(res_to["terminated_reason"], "timeout")
        with self.assertRaises(ProcessLookupError):
            _os.kill(res_to["child_pid"], 0)

        res_missing = run_bounded_command(
            ["/nonexistent_binary_xyz_12345"],
            allowed_executables={"nonexistent_binary_xyz_12345"},
        )
        self.assertFalse(res_missing["ok"])
        self.assertEqual(res_missing["returncode"], 127)
        self.assertEqual(res_missing["terminated_reason"], "executable_not_found")

        res_unsafe = run_bounded_command(["docker", "arg_with_\x00_null"])
        self.assertFalse(res_unsafe["ok"])
        self.assertEqual(res_unsafe["terminated_reason"], "invalid_arguments")

        for bad_bin in ("evil-binary", "escalation-wrapper", "arbitrary-tool"):
            res_blocked = run_bounded_command([bad_bin, "id"])
            self.assertFalse(res_blocked["ok"])
            self.assertEqual(res_blocked["terminated_reason"], "blocked_executable")



    def test_bug5_hetzner_primary_ipv4_zero_setup_fee_vs_additional_ip_setup_fee(self):
        res = cost_estimator.estimate_costs(self.saas)
        catalog = {r["id"]: r for r in res["metrics"]["verified_pricing_records"]}

        ax42_1 = catalog["hetzner-dedicated-ax42-1-standard"]
        self.assertEqual(ax42_1["price"], 97.30)
        self.assertEqual(ax42_1["setup_fee"], 49.00)
        self.assertEqual(ax42_1["ipv4_monthly_fee"], 1.70)
        self.assertEqual(ax42_1["ipv4_setup_fee"], 0.00)
        self.assertEqual(ax42_1["total_monthly_eur_with_ipv4"], 99.00)
        self.assertEqual(ax42_1["total_setup_eur_with_ipv4"], 49.00)

        ax42_2 = catalog["hetzner-dedicated-ax42-2-ecc"]
        self.assertEqual(ax42_2["ipv4_setup_fee"], 0.00)
        self.assertEqual(ax42_2["total_setup_eur_with_ipv4"], 49.00)

        # Verify separate Additional Single IPv4 add-on record holds the €4.90 setup fee
        self.assertIn("hetzner-dedicated-additional-single-ipv4", catalog)
        add_ip = catalog["hetzner-dedicated-additional-single-ipv4"]
        self.assertEqual(add_ip["offering_type"], "addon")
        self.assertEqual(add_ip["price"], 1.70)
        self.assertEqual(add_ip["setup_fee"], 4.90)

        # Verify deployment option uses 49.00 one-time setup EUR (not 53.90)
        opts = {o["option_id"]: o for o in res["metrics"]["deployment_options"]}
        self.assertEqual(opts["opt-hetzner-baremetal-ax42-1"]["recurring_monthly_eur_excl_vat"], 99.00)
        self.assertEqual(opts["opt-hetzner-baremetal-ax42-1"]["one_time_setup_eur_excl_vat"], 49.00)

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
                "import os, signal, sys, time\n"
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
                    allowed_executables={_os.path.basename(sys.executable)},
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
                "import os, signal, sys, time\n"
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
                    allowed_executables={_os.path.basename(sys.executable)},
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
                    allowed_executables={_os.path.basename(sys.executable)},
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



    def test_force_rescaffold_cleans_stale_runtime_and_redis_artifacts_and_error_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "rescaffold-target"
            # First scaffold Rust + Redis
            c_rs = dict(self.saas, team_experience="rust_postgres", expected_rps=600, monthly_budget_usd=500.0)
            res1 = scaffold_infrastructure.scaffold_project(c_rs, target, force=False)
            self.assertEqual(res1["status"], "ok")
            self.assertTrue((target / "Cargo.toml").exists())
            self.assertTrue((target / "config/redis.conf").exists())

            # Re-scaffold into the SAME directory with --force using Go + in_process cache
            c_go = dict(self.saas, team_experience="go_postgres", expected_rps=150, monthly_budget_usd=120.0)
            res2 = scaffold_infrastructure.scaffold_project(c_go, target, force=True)
            self.assertEqual(res2["status"], "ok")
            self.assertTrue((target / "go.mod").exists())
            self.assertFalse((target / "Cargo.toml").exists(), "Stale Cargo.toml should be removed on --force rescaffold")
            self.assertFalse((target / "config/redis.conf").exists(), "Stale redis.conf should be removed when redis_enabled=False")
            self.assertEqual(validate_blueprint.validate_scaffold(target)["status"], "ok")

    def test_security_allowlist_and_minimal_child_env(self):
        from common import ALLOWED_EXECUTABLES, build_child_env
        self.assertEqual(ALLOWED_EXECUTABLES, frozenset({"docker"}))
        res = run_bounded_command(["sh", "-c", "echo blocked"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["terminated_reason"], "blocked_executable")
        env = build_child_env(source_env={"PATH": "/usr/bin", "LANG": "C", "GITHUB_TOKEN": "secret"})
        self.assertEqual(env, {"PATH": "/usr/bin", "LANG": "C"})


if __name__ == "__main__":
    unittest.main()
