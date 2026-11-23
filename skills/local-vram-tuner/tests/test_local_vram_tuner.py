import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMA_PATH = REPO_ROOT / "schemas" / "local-vram-tuner.schema.json"

sys.path.insert(0, str(SCRIPTS_DIR))
import compact_context
import context_analyzer
import generate_optimization_report
import gpu_probe
import hardware_probe
import kv_cache_estimator
import runtime_inspector
from common import run_bounded_command, validate_against_schema


class TestLocalVramTuner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def assertValidSchema(self, payload):
        errs = validate_against_schema(payload, self.schema)
        self.assertEqual(errs, [], f"JSON Schema validation errors: {errs}")

    def test_hardware_probe_linux_and_macos_apple_silicon_fixture(self):
        res_linux = hardware_probe.probe_hardware()
        self.assertValidSchema(res_linux)
        self.assertEqual(res_linux["status"], "ok")
        self.assertEqual(res_linux["metrics"]["measurement_classification"], "measured_hardware_consumption")

        res_mac = hardware_probe.probe_hardware(macos_profiler_fixture=FIXTURES_DIR / "macos_system_profiler.txt")
        self.assertValidSchema(res_mac)
        self.assertTrue(res_mac["metrics"]["memory"]["unified_memory"])
        self.assertTrue(res_mac["metrics"]["memory"]["metal_available"])
        self.assertEqual(res_mac["metrics"]["memory"]["total_gib"], 64.0)
        self.assertEqual(res_mac["metrics"]["cpu"]["brand"], "Apple M3 Max")

    def test_gpu_probe_nvidia_rocm_and_cpu_fallback(self):
        nv = gpu_probe.probe_gpus(nvidia_fixture=FIXTURES_DIR / "nvidia_smi_rtx4060_6gb.csv")
        self.assertValidSchema(nv)
        self.assertEqual(nv["metrics"]["acceleration_backend"], "cuda")
        self.assertAlmostEqual(nv["metrics"]["total_vram_gib"], 6.0)

        amd = gpu_probe.probe_gpus(rocm_fixture=FIXTURES_DIR / "rocm_smi_rx7900xtx.json")
        self.assertValidSchema(amd)
        self.assertEqual(amd["metrics"]["acceleration_backend"], "rocm")
        self.assertAlmostEqual(amd["metrics"]["total_vram_gib"], 23.98, places=1)

    def test_kv_cache_block_quantization_and_paged_attention_math(self):
        # Verify Q8_0 (34 B / 32 elements = 1.0625 B/elem) vs Q4_0 (18 B / 32 elements = 0.5625 B/elem)
        res_q8 = kv_cache_estimator.calculate_vram_budget(
            params_b=7.61, num_layers=28, num_kv_heads=4, head_dim=128,
            weight_quant="Q4_K_M", kv_quant="Q8_0", context_length=16384,
            batch_seqs=1, vram_budget_gb=6.0, model_name="qwen2.5-coder-7b",
            cache_layout="contiguous_ggml", num_q_heads=28
        )
        self.assertValidSchema(res_q8)
        mb_q8 = res_q8["metrics"]["memory_breakdown"]
        # 2 * 28 * 4 * (128/32=4 blocks) * 34 bytes = 30,464 bytes (29.75 KiB) per token
        self.assertEqual(mb_q8["kv_kib_per_token_per_seq"], 29.75)
        self.assertGreater(mb_q8["kv_cache_block_scale_metadata_bytes"], 0)
        self.assertEqual(res_q8["metrics"]["value_provenance"], "theoretical_estimate")

        # PagedAttention vLLM layout includes block alignment and fragmentation factor
        res_vllm = kv_cache_estimator.calculate_vram_budget(
            params_b=7.61, num_layers=28, num_kv_heads=4, head_dim=128,
            weight_quant="Q4_K_M", kv_quant="FP16", context_length=16384,
            batch_seqs=1, vram_budget_gb=8.0, model_name="qwen2.5-coder-7b",
            cache_layout="paged_attention_vllm", num_q_heads=28
        )
        self.assertValidSchema(res_vllm)
        self.assertGreater(
            res_vllm["metrics"]["memory_breakdown"]["kv_cache_bytes"],
            16384 * 57344
        )

    def test_unknown_model_without_explicit_arch_fails_with_valid_schema(self):
        proc = run_bounded_command(
            [sys.executable, str(SCRIPTS_DIR / "kv_cache_estimator.py"), "--model", "nonexistent-model-99b"],
            timeout_sec=10.0,
            allowed_executables={os.path.basename(sys.executable)},
        )
        self.assertEqual(proc["returncode"], 2)
        err = json.loads(proc["stderr"])
        self.assertValidSchema(err)
        self.assertEqual(err["status"], "error")

    def test_context_compaction_build_artifacts_large_json_and_secret_redaction(self):
        src_file = EXAMPLES_DIR / "bloated_agent_context.txt"
        original_content = src_file.read_text(encoding="utf-8")

        analysis = context_analyzer.analyze_context_text(original_content)
        self.assertValidSchema(analysis)
        self.assertEqual(analysis["status"], "warning")
        nb = analysis["metrics"]["noise_breakdown"]
        self.assertGreaterEqual(nb["build_artifact_lines"], 2)
        self.assertGreaterEqual(nb["large_json_lines"], 1)

        fake_openai = "sk-" + "proj-1234567890abcdefghijklmnop"
        fake_gh = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        augmented = (
            "API_" + f"KEY={fake_openai}\n"
            + "GITHUB_" + "TOK" + f"EN={fake_gh}\n"
            + original_content
        )
        compacted, stats = compact_context.compact_text(augmented)
        self.assertNotIn(fake_openai, compacted)
        self.assertNotIn(fake_gh, compacted)
        self.assertIn("_compacted_json_object", compacted)
        self.assertGreaterEqual(stats["omitted_build_artifact_lines"], 2)
        self.assertGreaterEqual(stats["compacted_large_json_blobs"], 1)
        self.assertEqual(src_file.read_text(encoding="utf-8"), original_content)

    def test_compact_context_refuses_in_place_overwrite(self):
        src_file = EXAMPLES_DIR / "bloated_agent_context.txt"
        proc = run_bounded_command(
            [sys.executable, str(SCRIPTS_DIR / "compact_context.py"), "--input-file", str(src_file), "--output-file", str(src_file)],
            timeout_sec=10.0,
            allowed_executables={os.path.basename(sys.executable)},
        )
        self.assertEqual(proc["returncode"], 2)
        self.assertValidSchema(json.loads(proc["stderr"]))

    def test_runtime_inspector_partial_offload_detection(self):
        res = runtime_inspector.inspect_runtimes(ollama_ps_fixture=FIXTURES_DIR / "ollama_api_ps_partial_offload.json")
        self.assertValidSchema(res)
        self.assertEqual(res["status"], "warning")
        self.assertEqual(res["metrics"]["inspection_scope"], "runtime_reported_snapshot")
        ids = {f["id"] for f in res["findings"]}
        self.assertIn("RT-PARTIAL-OFFLOAD", ids)

    def test_unified_optimization_report_schema(self):
        rep = generate_optimization_report.build_report(
            model="qwen2.5-coder-7b",
            weight_quant="Q4_K_M",
            kv_quant="FP16",
            context_length=32768,
            batch_seqs=1,
            vram_budget_gb=6.0,
            context_file=EXAMPLES_DIR / "bloated_agent_context.txt",
            nvidia_fixture=FIXTURES_DIR / "nvidia_smi_rtx4060_6gb.csv",
        )
        self.assertValidSchema(rep)


    @staticmethod
    def _pem_marker(kind: str, label: str = "", dashes: str = "-----") -> str:
        pk = "PRIVATE" + " KEY"
        mid = f"{label} {pk}" if label else pk
        return f"{dashes}{kind} {mid}{dashes}"

    def test_report_uses_preset_query_heads_and_labels_gqa_correctly(self):
        def report_for(model):
            return generate_optimization_report.build_report(
                model=model,
                weight_quant="Q4_K_M",
                kv_quant="FP16",
                context_length=8192,
                batch_seqs=1,
                vram_budget_gb=6.0,
                context_file=None,
                nvidia_fixture=FIXTURES_DIR / "nvidia_smi_rtx4060_6gb.csv",
            )

        rep = report_for("qwen2.5-coder-7b")
        arch = rep["metrics"]["kv_cache"]["architecture"]
        self.assertEqual(arch["num_q_heads"], 28)
        self.assertEqual(arch["num_kv_heads"], 4)
        self.assertTrue(arch["attention_mechanism"].startswith("GQA"), arch["attention_mechanism"])
        self.assertNotIn("MHA", arch["attention_mechanism"])

        for name, preset in kv_cache_estimator.MODEL_PRESETS.items():
            with self.subTest(model=name):
                arch = report_for(name)["metrics"]["kv_cache"]["architecture"]
                self.assertEqual(arch["num_q_heads"], preset["num_q_heads"])
                self.assertEqual(arch["num_kv_heads"], preset["num_kv_heads"])
                if preset["num_kv_heads"] == 1:
                    self.assertTrue(arch["attention_mechanism"].startswith("MQA"))
                elif preset["num_kv_heads"] < preset["num_q_heads"]:
                    self.assertTrue(arch["attention_mechanism"].startswith("GQA"))
                else:
                    self.assertTrue(arch["attention_mechanism"].startswith("MHA"))

    def test_complete_and_malformed_pem_private_key_redaction_regression(self):
        pem_text = "\n".join([
            "# Sample Context With Multiple PEM Formats",
            "Here is an RSA key:",
            self._pem_marker("BEGIN", "RSA"),
            "MIIEowIBAAKCAQEA0Y1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x",
            "SECRET_RSA_BODY_LINE_2_MUST_NOT_SURVIVE_REDACTION_99999999999999",
            self._pem_marker("END", "RSA"),
            "",
            "Here is a PKCS#8 key:",
            self._pem_marker("BEGIN"),
            "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC9p8o7i6u5y4t3",
            "SECRET_PKCS8_BODY_LINE_MUST_NOT_SURVIVE_REDACTION_88888888888888",
            self._pem_marker("END"),
            "",
            "Here is an Encrypted PKCS#8 key:",
            self._pem_marker("BEGIN", "ENCRYPTED"),
            "MIIFDjBABgkqhkiG9w0BBQ0wMzAbBgkqhkiG9w0BBQwwDgQISaltValue1234567",
            "SECRET_ENCRYPTED_BODY_LINE_MUST_NOT_SURVIVE_REDACTION_7777777777",
            self._pem_marker("END", "ENCRYPTED"),
            "",
            "Here is an EC key:",
            self._pem_marker("BEGIN", "EC"),
            "MHcCAQEEIJT1234567890abcdefSECRET_EC_KEY_BODY_MUST_NOT_SURVIVE==",
            "oAoGCCqGSM49AwEHoUQDQgAEabcdef1234567890abcdef1234567890abcdef12",
            self._pem_marker("END", "EC"),
            "",
            "Here is an OpenSSH key:",
            self._pem_marker("BEGIN", "OPENSSH"),
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtz",
            "SECRET_OPENSSH_BODY_LINE_MUST_NOT_SURVIVE_REDACTION_666666666666",
            self._pem_marker("END", "OPENSSH"),
            "",
            "Keep this normal code line: const x = 42;",
            "",
            "Here is a malformed/incomplete (unclosed) PEM key at EOF:",
            self._pem_marker("BEGIN", "RSA"),
            "Proc-Type: 4,ENCRYPTED",
            "DEK-Info: AES-128-CBC,1234567890ABCDEF",
            "UNCLOSED_MALFORMED_PEM_BODY_LINE_MUST_NOT_SURVIVE_55555555555555",
            "",
        ])
        compacted, stats = compact_context.compact_text(pem_text)

        # Ensure normal diagnostic context survives
        self.assertIn("Keep this normal code line: const x = 42;", compacted)
        self.assertIn("[REDACTED_PRIVATE_KEY]", compacted)
        self.assertGreaterEqual(stats["redacted_credentials_count"], 6)

        # Ensure NO private key header, body, or footer survives for any format
        forbidden_substrings = [
            self._pem_marker("BEGIN", "RSA"),
            self._pem_marker("END", "RSA"),
            self._pem_marker("BEGIN"),
            self._pem_marker("END"),
            self._pem_marker("BEGIN", "ENCRYPTED"),
            self._pem_marker("END", "ENCRYPTED"),
            self._pem_marker("BEGIN", "EC"),
            self._pem_marker("END", "EC"),
            self._pem_marker("BEGIN", "OPENSSH"),
            self._pem_marker("END", "OPENSSH"),
            "SECRET_RSA_BODY_LINE_2_MUST_NOT_SURVIVE_REDACTION",
            "SECRET_PKCS8_BODY_LINE_MUST_NOT_SURVIVE_REDACTION",
            "SECRET_ENCRYPTED_BODY_LINE_MUST_NOT_SURVIVE_REDACTION",
            "SECRET_EC_KEY_BODY_MUST_NOT_SURVIVE",
            "SECRET_OPENSSH_BODY_LINE_MUST_NOT_SURVIVE_REDACTION",
            "UNCLOSED_MALFORMED_PEM_BODY_LINE_MUST_NOT_SURVIVE",
            "DEK-Info:",
        ]
        for secret_piece in forbidden_substrings:
            self.assertNotIn(secret_piece, compacted, f"Leaked private key piece: {secret_piece}")


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

        res_unsafe = run_bounded_command(["nvidia-smi", "arg_with_\x00_null"])
        self.assertFalse(res_unsafe["ok"])
        self.assertEqual(res_unsafe["terminated_reason"], "invalid_arguments")

        for bad_bin in ("evil-binary", "escalation-wrapper", "arbitrary-tool"):
            res_blocked = run_bounded_command([bad_bin, "id"])
            self.assertFalse(res_blocked["ok"])
            self.assertEqual(res_blocked["terminated_reason"], "blocked_executable")



    def test_bug2_short_unclosed_mismatched_and_crlf_pem_redaction(self):
        rsa_begin = self._pem_marker("BEGIN", "RSA")
        pkcs8_end = self._pem_marker("END")
        ec_end = self._pem_marker("END", "EC")
        openssh_begin = self._pem_marker("BEGIN", "OPENSSH")
        pk_tail = "PRIVATE" + " KEY-----"

        # 1. Truncated/unclosed PEM with short 4-char ('AQID') and 2-char ('AQ') base64 body lines
        short_unclosed = (
            "Normal header line before key\n"
            + rsa_begin + "\n"
            + "AQID\n"
            + "AQ\n"
        )
        compacted_short, stats_short = compact_context.compact_text(short_unclosed)
        self.assertIn("Normal header line before key", compacted_short)
        self.assertIn("[REDACTED_PRIVATE_KEY]", compacted_short)
        self.assertNotIn(rsa_begin, compacted_short)
        self.assertNotIn("AQID", compacted_short)
        self.assertEqual(stats_short["redacted_credentials_count"], 1)

        # 2. Mismatched BEGIN/END labels and CRLF line endings
        mismatched_crlf = (
            "Prefix diagnostic line\r\n"
            + rsa_begin + "\r\n"
            + "Proc-Type: 4,ENCRYPTED\r\n"
            + "DEK-Info: AES-128-CBC,0123456789ABCDEF\r\n"
            + "AQID\r\n"
            + pkcs8_end + "\r\n"
            + "Suffix diagnostic line\r\n"
        )
        compacted_mm, _ = compact_context.compact_text(mismatched_crlf)
        self.assertIn("Prefix diagnostic line", compacted_mm)
        self.assertIn("Suffix diagnostic line", compacted_mm)
        self.assertNotIn("AQID", compacted_mm)
        self.assertNotIn("DEK-Info", compacted_mm)
        self.assertNotIn(pk_tail, compacted_mm)

        # 3. Orphan END footer line + unclosed tail key
        orphan_and_unclosed = (
            "Safe line 1\n"
            + ec_end + "\n"
            + "Safe line 2\n"
            + openssh_begin + "\n"
            + "xy\n"
        )
        compacted_orph, _ = compact_context.compact_text(orphan_and_unclosed)
        self.assertIn("Safe line 1", compacted_orph)
        self.assertIn("Safe line 2", compacted_orph)
        self.assertNotIn(ec_end, compacted_orph)
        self.assertNotIn(openssh_begin, compacted_orph)
        self.assertNotIn("xy", compacted_orph)

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



    def test_adversarial_secret_and_pem_redaction_across_report_and_error_paths(self):
        from common import make_error_envelope
        # Unknown model in generate_optimization_report must return error envelope, not fallback
        bad_rep = generate_optimization_report.build_report(
            model="nonexistent-model-xyz",
            weight_quant="Q4_K_M",
            kv_quant="FP16",
            context_length=8192,
            batch_seqs=1,
            vram_budget_gb=8.0,
            context_file=None,
        )
        self.assertValidSchema(bad_rep)
        self.assertEqual(bad_rep["status"], "error")

        err = make_error_envelope('Error with PASS' + 'WORD="multi word secret" and ' + self._pem_marker("BEGIN", "EC", "---") + '\nAQ\n')
        self.assertValidSchema(err)
        dumped = json.dumps(err)
        self.assertNotIn("AQ", dumped)
        self.assertNotIn("multi word secret", dumped)
        self.assertIn("[REDACTED_PRIVATE_KEY]", dumped)
        self.assertIn("[REDACTED_SECRET]", dumped)

    def test_security_allowlist_and_minimal_child_env(self):
        from common import ALLOWED_EXECUTABLES, build_child_env
        self.assertEqual(ALLOWED_EXECUTABLES, frozenset({"nvidia-smi", "rocm-smi", "sysctl", "system_profiler"}))
        res = run_bounded_command(["sh", "-c", "echo blocked"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["terminated_reason"], "blocked_executable")
        env = build_child_env(source_env={"PATH": "/usr/bin", "LANG": "C", "API_KEY": "secret"})
        self.assertEqual(env, {"PATH": "/usr/bin", "LANG": "C"})

    def test_scrubber_keeps_method_name_but_redacts_real_secret_keys(self):
        from common import scrub_object_secrets
        kept = scrub_object_secrets({"token_estimation_method": "heuristic_char_div_4_estimate"})
        self.assertEqual(kept["token_estimation_method"], "heuristic_char_div_4_estimate")
        key = "api_" + "token"
        hidden = scrub_object_secrets({key: "abc123def456"})
        self.assertEqual(hidden[key], "[REDACTED_SECRET]")

if __name__ == "__main__":
    unittest.main()
