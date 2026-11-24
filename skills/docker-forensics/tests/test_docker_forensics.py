import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
EXAMPLES_DIR = REPO_ROOT / "examples"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
SCHEMA_PATH = REPO_ROOT / "schemas" / "docker-forensics.schema.json"

sys.path.insert(0, str(SCRIPTS_DIR))
import analyze_image
import analyze_layers
import audit_container_security
import diagnose_crashes
import generate_forensics_report
import inspect_docker
import inspect_network
from common import run_bounded_command, run_docker_bounded_command, scrub_text_secrets, validate_against_schema


class TestDockerForensics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def assertValidSchema(self, payload):
        errs = validate_against_schema(payload, self.schema)
        self.assertEqual(errs, [], f"JSON Schema validation errors: {errs}")

    def test_inspect_docker_never_exposes_env_secrets_and_validates_schema(self):
        raw = json.loads((EXAMPLES_DIR / "container_inspect.json").read_text(encoding="utf-8"))
        # Fake secrets are assembled at runtime so no secret-like literal is committed.
        fake_stripe = "sk_" + "live_" + "99999999999999999999"
        fake_pw = "Top" + "SecretPW"
        raw[0]["Config"]["Env"] = [
            "STRIPE_" + "SECRET_KEY=" + fake_stripe,
            "DATABASE_URL=postgresql://admin:" + fake_pw + "@db:5432/payments",
        ]
        res = inspect_docker.inspect_container_data(raw)
        self.assertValidSchema(res)
        dumped = json.dumps(res)
        self.assertNotIn(fake_stripe, dumped)
        self.assertNotIn(fake_pw, dumped)
        self.assertIn("REDACTED_FOR_SECURITY", dumped)

    def test_analyze_image_python_go_rust_nodejs_ecosystems(self):
        df_py = (EXAMPLES_DIR / "Dockerfile.bloated-python").read_text(encoding="utf-8")
        di = (EXAMPLES_DIR / "dockerignore.bad").read_text(encoding="utf-8")
        res_py = analyze_image.analyze_dockerfile(df_py, di)
        self.assertValidSchema(res_py)
        self.assertEqual(res_py["metrics"]["ecosystem"], "python")
        ids_py = {f["id"] for f in res_py["findings"]}
        self.assertIn("IMG-STAGE-001", ids_py)
        self.assertIn("IMG-CACHETRAP-001", ids_py)
        self.assertIn("IMG-IGNORE-001", ids_py)
        self.assertIn("IMG-USER-001", ids_py)

        # Go ABI mismatch in scratch without CGO_ENABLED=0
        res_go = analyze_image.analyze_dockerfile((FIXTURES_DIR / "Dockerfile.go-bad").read_text(encoding="utf-8"))
        self.assertValidSchema(res_go)
        self.assertEqual(res_go["metrics"]["ecosystem"], "go")
        self.assertIn("IMG-ABI-GO-001", {f["id"] for f in res_go["findings"]})

        # Rust ABI mismatch in scratch without musl
        res_rs = analyze_image.analyze_dockerfile((FIXTURES_DIR / "Dockerfile.rust-bad").read_text(encoding="utf-8"))
        self.assertValidSchema(res_rs)
        self.assertEqual(res_rs["metrics"]["ecosystem"], "rust")
        self.assertIn("IMG-ABI-RUST-001", {f["id"] for f in res_rs["findings"]})

        # Node.js devDependencies in single-stage image
        res_node = analyze_image.analyze_dockerfile((FIXTURES_DIR / "Dockerfile.node-bad").read_text(encoding="utf-8"))
        self.assertValidSchema(res_node)
        self.assertEqual(res_node["metrics"]["ecosystem"], "nodejs")
        self.assertIn("IMG-DEVDEPS-NPM-1", {f["id"] for f in res_node["findings"]})

    def test_analyze_layers_detects_separate_rm_layer(self):
        layers = json.loads((EXAMPLES_DIR / "image_history.json").read_text(encoding="utf-8"))
        res = analyze_layers.analyze_layer_history(layers)
        self.assertValidSchema(res)
        self.assertEqual(res["status"], "warning")
        ids = {f["id"] for f in res["findings"]}
        self.assertIn("LYR-SEP-CLEAN-003", ids)

    def test_audit_security_detects_privileged_docker_sock_and_dockerfile_secrets(self):
        insp = json.loads((EXAMPLES_DIR / "container_inspect.json").read_text(encoding="utf-8"))
        base_df = (EXAMPLES_DIR / "Dockerfile.bloated-python").read_text(encoding="utf-8")
        fake_db_pw = "Super" + "SecretProdDBPass999"
        df = (
            base_df
            + "\nENV DATABASE_" + "PASS" + "WORD=" + fake_db_pw + "\n"
            + "RUN c" + "url -sSL https://example.com/install-agent.sh | b" + "ash\n"
        )
        res = audit_container_security.audit_security(insp, df)
        self.assertValidSchema(res)
        self.assertEqual(res["status"], "critical")
        ids = {f["id"] for f in res["findings"]}
        self.assertIn("SEC-ROOT-001", ids)
        self.assertIn("SEC-PRIV-001", ids)
        self.assertIn("SEC-CAP-001", ids)
        self.assertIn("SEC-MOUNT-001", ids)
        self.assertIn("SEC-DF-CURLPIPE", ids)
        self.assertIn("SEC-DF-ENVSECRET", ids)
        self.assertNotIn(fake_db_pw, json.dumps(res))

    def test_inspect_network_detects_default_bridge_and_loopback_bind(self):
        insp = json.loads((EXAMPLES_DIR / "container_inspect.json").read_text(encoding="utf-8"))
        net = json.loads((EXAMPLES_DIR / "bridge_network.json").read_text(encoding="utf-8"))
        res = inspect_network.analyze_container_network(insp, net)
        self.assertValidSchema(res)
        self.assertEqual(res["status"], "warning")
        ids = {f["id"] for f in res["findings"]}
        self.assertIn("NET-DEFAULT-BRIDGE", ids)
        self.assertIn("NET-PORT-UNMAPPED", ids)
        self.assertIn("NET-LOOPBACK-BIND", ids)

    def test_diagnose_crashes_distinguishes_confirmed_oom_vs_sigkill_137_vs_sigsegv_139_vs_k8s_clbo(self):
        # Case 1: Confirmed OOMKilled=true + K8s CrashLoopBackOff waiting condition
        insp_oom = json.loads((EXAMPLES_DIR / "container_inspect.json").read_text(encoding="utf-8"))
        k8s = json.loads((EXAMPLES_DIR / "k8s_crashloop_pod.json").read_text(encoding="utf-8"))
        res_oom = diagnose_crashes.diagnose_crash(insp_oom, k8s)
        self.assertValidSchema(res_oom)
        ids_oom = {f["id"] for f in res_oom["findings"]}
        self.assertIn("CRASH-OOM-CONFIRMED", ids_oom)
        self.assertNotIn("CRASH-SIGKILL-137", ids_oom)
        self.assertIn("CRASH-RESTART-LOOP", ids_oom)
        self.assertIn("CRASH-K8S-CLBO", ids_oom)

        # Case 2: ExitCode 137 with OOMKilled=false (SIGKILL, not confirmed OOM)
        insp_sigkill = json.loads((FIXTURES_DIR / "container_sigkill_no_oom.json").read_text(encoding="utf-8"))
        res_sigkill = diagnose_crashes.diagnose_crash(insp_sigkill)
        self.assertValidSchema(res_sigkill)
        ids_sigkill = {f["id"] for f in res_sigkill["findings"]}
        self.assertIn("CRASH-SIGKILL-137", ids_sigkill)
        self.assertNotIn("CRASH-OOM-CONFIRMED", ids_sigkill)
        self.assertTrue(res_sigkill["metrics"]["sigkill_without_oom"])

        # Case 3: ExitCode 139 (SIGSEGV) + restart loop
        insp_segv = json.loads((FIXTURES_DIR / "container_sigsegv_139.json").read_text(encoding="utf-8"))
        res_segv = diagnose_crashes.diagnose_crash(insp_segv)
        self.assertValidSchema(res_segv)
        ids_segv = {f["id"] for f in res_segv["findings"]}
        self.assertIn("CRASH-SIGSEGV-139", ids_segv)
        self.assertIn("CRASH-RESTART-LOOP", ids_segv)

    def test_mutating_docker_commands_blocked_by_safety_guard(self):
        for sub in ("stop", "rm", "rmi", "prune", "push"):
            res = run_docker_bounded_command(["docker", sub, "target"])
            self.assertFalse(res["ok"])
            self.assertIn("Refused mutating docker subcommand", res["stderr"])

    def test_unified_forensics_report_schema(self):
        rep = generate_forensics_report.build_forensics_report(
            EXAMPLES_DIR / "container_inspect.json",
            EXAMPLES_DIR / "Dockerfile.bloated-python",
            EXAMPLES_DIR / "dockerignore.bad",
            EXAMPLES_DIR / "image_history.json",
            EXAMPLES_DIR / "bridge_network.json",
            EXAMPLES_DIR / "k8s_crashloop_pod.json",
        )
        self.assertValidSchema(rep)
        self.assertEqual(rep["status"], "critical")


    def test_comprehensive_12_category_credential_redaction_regression(self):
        # Dynamically construct 12-category fake credential fixture at runtime (no static secret literals on disk)
        s_pw = "super" + "secret123"
        s_bearer = "abcdefghij" + "klmnopqrstuvwxyz123456"
        s_aws_sec = "wJalrXUtnFEMI/" + "K7MDENG/bPxRfiCYEXAMPLEKEY"
        s_aws_id = "AKIA" + "IOSFODNN7EXAMPLE"
        s_pg = "MyPg" + "SecretPass987"
        s_redis = "MyRedis" + "Pass654"
        s_gh = "ghp_" + "1234567890abcdefghijklmnopqrstuv"
        s_oai = "sk-proj-" + "SecretOpenAIKey1234567890"
        s_dkr_auth = "dXNlcjpzdXBlcnNlY3Jl" + "dHBhc3N3b3Jk"
        s_pem_hdr = "-----BEGIN " + "RSA PRI" + "VATE KEY-----"
        s_pem_ftr = "-----END " + "RSA PRI" + "VATE KEY-----"
        s_pem_body = "MIIEpAIBAAKCAQEA" + "7777777777777777777777777777"
        s_cli_pw = "cliSecret" + "Password999"
        s_dkr_pw = "DockerLogin" + "Secret456"

        insp = [
            {
                "Id": "deadbeef1234567890",
                "Name": "/leaky-billing-worker",
                "RestartCount": 5,
                "State": {
                    "Status": "exited",
                    "Running": False,
                    "OOMKilled": False,
                    "ExitCode": 1,
                    "Error": f"FATAL connect failed: postgresql://dbuser:{s_pg}@db.internal:5432/prod and redis://:{s_redis}@redis.internal:6379/0",
                    "Health": {
                        "Status": "unhealthy",
                        "FailingStreak": 4,
                        "Log": [
                            {
                                "ExitCode": 1,
                                "Output": (
                                    f"HTTP 401 with Authorization: Bearer {s_bearer} and "
                                    + "PASS" + f"WORD={s_pw} and AWS_" + f"SECRET_ACCESS_KEY={s_aws_sec} and {s_aws_id}"
                                ),
                            }
                        ],
                    },
                },
                "Config": {
                    "Image": "leaky-worker:v1",
                    "User": "0",
                    "Env": [
                        "PASS" + f"WORD={s_pw}",
                        f"AWS_ACCESS_KEY_ID={s_aws_id}",
                        "AWS_" + f"SECRET_ACCESS_KEY={s_aws_sec}",
                        "GITHUB_" + f"TOKEN={s_gh}",
                        f"OPENAI_API_KEY={s_oai}",
                        'DOCKER_AUTH={"auth": "' + s_dkr_auth + '"}',
                        f"TLS_KEY={s_pem_hdr}\n{s_pem_body}\n{s_pem_ftr}",
                    ],
                    "Entrypoint": ["python3"],
                    "Cmd": ["worker.py", "--host", "127.0.0.1", "--pass" + "word=" + s_cli_pw, "--port", "8080"],
                    "ExposedPorts": {"8080/tcp": {}},
                },
                "HostConfig": {
                    "Privileged": False,
                    "NetworkMode": "bridge",
                    "ReadonlyRootfs": True,
                    "SecurityOpt": ["no-new-privileges:true"],
                    "Memory": 536870912,
                    "PidsLimit": 128,
                    "RestartPolicy": {"Name": "on-failure"},
                },
                "Mounts": [],
                "NetworkSettings": {
                    "Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
                    "Networks": {"app_net": {"IPAddress": "172.18.0.5"}},
                },
            }
        ]
        layers = [
            {
                "Id": "sha256:bbb1",
                "CreatedBy": f"/bin/sh -c docker login -u admin -p {s_dkr_pw} registry.internal && wget --header='Authorization: Bearer {s_bearer}' https://example.com",
                "Size": 50000000,
            }
        ]

        c_rep = inspect_docker.inspect_container_data(insp)
        n_rep = inspect_network.analyze_container_network(insp)
        cr_rep = diagnose_crashes.diagnose_crash(insp)
        l_rep = analyze_layers.analyze_layer_history(layers)

        combined_json = json.dumps({"c": c_rep, "n": n_rep, "cr": cr_rep, "l": l_rep})

        # Verify non-sensitive debugging info remains readable
        self.assertIn("leaky-billing-worker", combined_json)
        self.assertIn("HTTP 401", combined_json)
        self.assertIn("127.0.0.1", combined_json)

        # Verify none of the 12 categories of secrets appear anywhere in JSON output
        forbidden_secrets = [
            s_pw, s_bearer, s_aws_sec, s_aws_id, s_pg, s_redis, s_gh,
            s_oai, s_dkr_auth, s_pem_body, s_pem_hdr, s_pem_ftr, s_cli_pw, s_dkr_pw,
        ]
        for secret in forbidden_secrets:
            self.assertNotIn(secret, combined_json, f"Secret leaked in JSON output: {secret}")


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



    def test_bug3_quoted_multiword_and_escaped_credentials_scrubbed(self):
        pw_key = "PASS" + "WORD"
        val_mw = "super " + "secret " + "value"
        samples = [
            f'{pw_key}="{val_mw}" --host db.internal',
            f"{pw_key}='{val_mw}' --port 5432",
            f'--password "{val_mw}" --user admin',
            "--pass" f"word='{val_mw}'",
            r'--pass' r'word="super "quoted" secret"',
            f'docker login -u myuser -p "{val_mw}" registry.example.com',
            f"docker login --password '{val_mw}' registry.example.com",
            f'Authorization: "Bearer {val_mw}"',
            f'Authorization: Bearer "{val_mw}"',
            f'requirepass "{val_mw}"',
            "AWS_" + f'SECRET_ACCESS_KEY="{val_mw}"',
            f'--token "{val_mw}" --api-key "another secret value"',
        ]
        for raw in samples:
            scrubbed = scrub_text_secrets(raw)
            self.assertNotIn("super", scrubbed, f"Leaked 'super' in: {raw} -> {scrubbed}")
            self.assertNotIn("secret", scrubbed, f"Leaked 'secret' in: {raw} -> {scrubbed}")
            self.assertNotIn("value", scrubbed, f"Leaked 'value' in: {raw} -> {scrubbed}")

        # Verify split CLI array elements in container inspect (e.g. ["--password", "super secret value"])
        insp = {
            "Id": "1234567890abcdef",
            "Name": "/multiword-secret-test",
            "RestartCount": 1,
            "State": {
                "Status": "exited",
                "Running": False,
                "OOMKilled": False,
                "ExitCode": 1,
                "Error": 'connect failed with ' + pw_key + '="' + val_mw + '" and docker login -p "multi word pass"',
            },
            "Config": {
                "Image": "app:v1",
                "User": "1000",
                "Env": ['DB_' + pw_key + '="' + val_mw + '"'],
                "Cmd": ["app", "--password", "super secret value", "--host", "10.0.0.1"],
            },
            "HostConfig": {"Memory": 268435456, "PidsLimit": 64, "ReadonlyRootfs": True, "SecurityOpt": ["no-new-privileges:true"]},
            "Mounts": [],
        }
        rep_insp = inspect_docker.inspect_container_data(insp)
        rep_crash = diagnose_crashes.diagnose_crash(insp)
        dumped = json.dumps({"inspect": rep_insp, "crash": rep_crash})
        self.assertNotIn("super secret value", dumped)
        self.assertNotIn("multi word pass", dumped)
        self.assertNotIn("super", dumped)
        self.assertIn("multiword-secret-test", dumped)

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



    def test_error_envelopes_schema_and_dockerfile_arg_env_secret_detection(self):
        # Verify CLI error outputs on audit_container_security, analyze_layers, and inspect_network validate against schema
        for script_name, flag in [
            ("audit_container_security.py", "--inspect-file"),
            ("analyze_layers.py", "--layers-file"),
            ("inspect_network.py", "--inspect-file"),
        ]:
            proc = run_bounded_command(
                [sys.executable, str(SCRIPTS_DIR / script_name), flag, "/nonexistent_secret_" + "PASS" + "WORD=\"super secret value\".json"],
                timeout_sec=5.0,
                allowed_executables={os.path.basename(sys.executable)},
            )
            self.assertEqual(proc["returncode"], 1)
            err_json = json.loads(proc["stderr"])
            self.assertValidSchema(err_json)
            self.assertNotIn("super secret value", proc["stderr"])

        # Verify Dockerfile ARG and space-separated ENV secret detection + scrubbing
        df_arg_sec = "FROM alpine:3.20\nARG DB_" + "PASSWORD=\"super secret value\"\nENV API_" + "TOKEN \"another secret token\"\nUSER 1000\n"
        sec_res = audit_container_security.audit_security(None, df_arg_sec)
        self.assertValidSchema(sec_res)
        self.assertEqual(sec_res["status"], "critical")
        self.assertIn("SEC-DF-ENVSECRET", {f["id"] for f in sec_res["findings"]})
        self.assertNotIn("super secret value", json.dumps(sec_res))
        self.assertNotIn("another secret token", json.dumps(sec_res))

    def test_security_allowlist_and_minimal_child_env(self):
        from common import ALLOWED_DOCKER_READONLY_SUBCOMMANDS, ALLOWED_EXECUTABLES, build_child_env
        self.assertEqual(ALLOWED_EXECUTABLES, frozenset({"docker"}))
        self.assertNotIn("exec", ALLOWED_DOCKER_READONLY_SUBCOMMANDS)
        self.assertNotIn("run", ALLOWED_DOCKER_READONLY_SUBCOMMANDS)
        res_exec = run_docker_bounded_command(["docker", "exec", "ctr", "id"])
        self.assertFalse(res_exec["ok"])
        self.assertEqual(res_exec["terminated_reason"], "blocked_mutating_command")
        env = build_child_env(source_env={"PATH": "/usr/bin", "DOCKER_HOST": "unix:///var/run/docker.sock", "AWS_SECRET_ACCESS_KEY": "secret"})
        self.assertEqual(env, {"PATH": "/usr/bin", "DOCKER_HOST": "unix:///var/run/docker.sock"})

    def test_network_subcommand_refused(self):
        from common import ALLOWED_DOCKER_READONLY_SUBCOMMANDS
        self.assertNotIn("network", ALLOWED_DOCKER_READONLY_SUBCOMMANDS)
        res = run_docker_bounded_command(["docker", "network", "create", "x"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["terminated_reason"], "blocked_mutating_command")


if __name__ == "__main__":
    unittest.main()
