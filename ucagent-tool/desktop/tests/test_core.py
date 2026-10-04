"""Python 3.8 contracts for transport, literal input validation, and safe local artifacts."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ucagent_tk.client import ApiClient, ApiError, Cancelled, collection, segment, validate_origin
from ucagent_tk.i18n import tr
from ucagent_tk.model import Preferences, initial_draft, next_action, seeds, validate_draft
from ucagent_tk.widgets import display
from fakes import ARTIFACT, PlatformServer, PROJECT, RUN, WAVEFORM


class ModelTests(unittest.TestCase):
    """Prove desktop validation preserves evidence semantics and canonical saved requests."""

    def test_formalmc_uses_one_tcl_and_no_ignored_timing(self):
        """Accept the original Tcl contract and reject missing or ambiguous entry points."""
        draft = initial_draft(PROJECT)
        draft.pop("simulation", None)
        draft.update(family="formal", formal={"engine": "formalmc", "clock": {}, "reset": {}, "property_sets": ["DUT_formal.tcl"]})
        self.assertEqual(validate_draft(draft)["formal"]["engine"], "formalmc")
        for scripts in ([], ["properties.sv"], ["one.tcl", "two.tcl"]):
            draft["formal"]["property_sets"] = scripts
            with self.assertRaisesRegex(ValueError, "exactly one"):
                validate_draft(draft)
        draft["formal"].update(property_sets=["run.tcl"], clock={"signal": "clk"})
        with self.assertRaisesRegex(ValueError, "Tcl script"):
            validate_draft(draft)

    def test_sby_requires_harness_not_guessed_signal_names(self):
        """Accept bounded SBY settings without imposing VC Formal's timing inputs."""
        draft = initial_draft(PROJECT)
        draft.pop("simulation", None)
        draft.update(family="formal", methodology="systemverilog", formal={"engine": "sby", "clock": {}, "reset": {}, "sby": {"mode": "bmc", "depth": 10, "timeout_seconds": 30}})
        self.assertEqual(validate_draft(draft)["formal"]["sby"]["mode"], "bmc")
        for value in (0, -1, True, 100001, "40"):
            draft["formal"]["sby"]["depth"] = value
            with self.assertRaises(ValueError):
                validate_draft(draft)

    def test_origin_boundaries(self):
        """Reject secrets, arbitrary paths, and non-loopback unencrypted destinations."""
        for value in ("http://127.0.0.1:8800/", "https://eda.example", "http://[::1]:8800"):
            self.assertEqual(validate_origin(value), value.rstrip("/"))
        for value in ("http://192.168.31.116:8800", "http://user:password@localhost", "http://localhost/api", "http://localhost?token=x", "ftp://localhost", "http://localhost:70000", "http://localhost\n"):
            with self.subTest(value=value), self.assertRaises(ApiError):
                validate_origin(value)

    def test_seeds_are_strict_positive(self):
        """Do not silently drop invalid seed tokens or impose an undocumented 32-bit bound."""
        self.assertEqual(seeds("11, 29\n11"), [11, 29])
        self.assertEqual(seeds("2147483648"), [2147483648])
        for value in ("", "0", "-1", "1e3", "3.5", "1;echo", "1,broken", "True"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                seeds(value)

    def test_draft_isolation_and_scope(self):
        """Copy rather than mutate saved defaults and reject empty real-test selections."""
        draft = initial_draft(PROJECT)
        draft["design"]["parameters"]["WIDTH"] = 99
        self.assertEqual(PROJECT["design"]["parameters"]["WIDTH"], 8)
        draft["methodology"] = "uvm"
        draft["simulation"]["tests"] = []
        with self.assertRaisesRegex(ValueError, "real UVM"):
            validate_draft(draft)
        draft["methodology"] = "unitytest"
        with self.assertRaisesRegex(ValueError, "pytest"):
            validate_draft(draft)
        with self.assertRaisesRegex(ValueError, "run_defaults"):
            initial_draft({"id": "missing"})

    def test_formal_requires_clock_and_reset(self):
        """Do not submit proof requests whose timing environment is implicit."""
        draft = initial_draft(PROJECT)
        draft.update(family="formal", formal={"engine": "vc_formal", "clock": {}, "reset": {}})
        with self.assertRaisesRegex(ValueError, "clock and reset"):
            validate_draft(draft)

    def test_result_and_execution_are_orthogonal(self):
        """Completed failed tests lead to evidence; license failures lead to infrastructure."""
        self.assertEqual(next_action({**RUN, "verification_status": "failed"}), ("action_failure", "tests"))
        self.assertEqual(next_action({**RUN, "verification_status": "failed", "family": "formal"}), ("action_cex", "properties"))
        self.assertEqual(next_action({**RUN, "execution_status": "timeout"})[1], "jobs")
        self.assertEqual(next_action({**RUN, "summary": {"diagnostic_code": "license_unavailable"}})[0], "action_license")
        self.assertEqual(next_action({**RUN, "execution_status": "running"})[1], "logs")

    def test_literal_braces_and_markup_are_not_evaluated(self):
        """Treat tool commands, source templates and markup as literal display data."""
        self.assertEqual(tr("{WORKSPACE}/rtl/{DUT}.sv"), "{WORKSPACE}/rtl/{DUT}.sv")
        self.assertEqual(tr("<script>alert(1)</script>"), "<script>alert(1)</script>")
        self.assertEqual(segment("run:wf/stage"), "run%3Awf%2Fstage")

    def test_table_identities_are_not_translated_as_actions(self):
        """Tool names and user test names remain literal even if they match localization keys."""
        for name in ("verdi", "error", "running", "passed", "{DUT}", "overview"):
            self.assertEqual(display(name, "name"), name)
        self.assertEqual(display("failed", "verification_status"), tr("failed"))
        self.assertEqual(display("error", "execution_status"), tr("error_status"))
        self.assertEqual(display(True, "available"), tr("available"))
        self.assertEqual(display(None, "coverage"), "--")

    def test_malformed_collection_is_not_empty(self):
        """Fail on incorrect contracts rather than presenting an apparently empty platform."""
        for payload in (None, [], {"items": None}, {"items": ["bad"]}):
            with self.assertRaises(ApiError):
                collection(payload)
        self.assertEqual(collection({"items": []}), [])

    def test_preferences_ignore_secrets_and_bad_origins(self):
        """Persist only origin and bounded cursors, recovering safely from corrupt settings."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text(json.dumps({"origin": "http://password@localhost", "password": "fixture-secret"}), encoding="utf-8")
            self.assertEqual(Preferences(path).origin, "http://127.0.0.1:8800")
            path.write_text(json.dumps({"origin": "http://localhost:8800", "password": "fixture-secret", "cursors": {"run-1": 100, "../bad": 8, "negative": -1}}), encoding="utf-8")
            preferences = Preferences(path)
            self.assertEqual(preferences.cursors, {"run-1": 100})
            preferences.save()
            self.assertEqual(set(json.loads(path.read_text())), {"origin", "cursors"})
            self.assertNotIn("fixture-secret", path.read_text())


class TransportTests(unittest.TestCase):
    """Exercise real HTTP, SSE, multipart input, and local atomic download behavior."""

    def setUp(self):
        """Create an isolated HTTP service and temporary output directory."""
        self.server = PlatformServer()
        self.client = ApiClient(self.server.origin)
        self.directory = tempfile.TemporaryDirectory()
        self.target = Path(self.directory.name) / "wave.fsdb"

    def tearDown(self):
        """Close only test-owned sockets and directories."""
        self.server.close()
        self.directory.cleanup()

    def test_get_and_structured_post_same_origin(self):
        """Preserve typed requests and the origin required by server CSRF protection."""
        self.assertEqual(collection(self.client.call("/projects"))[0]["id"], PROJECT["id"])
        self.client.call("/runs/preview", "POST", PROJECT["run_defaults"])
        self.assertEqual(self.server.mutations[0][2], PROJECT["run_defaults"])
        self.assertTrue(all(row[2] == self.server.origin for row in self.server.requests))

    def test_redirect_malformed_and_validation_error(self):
        """Reject redirects and malformed JSON while surfacing structured server validation."""
        for path in ("/redirect", "/malformed", "//external", "https://elsewhere/"):
            with self.subTest(path=path), self.assertRaises(ApiError):
                self.client.call(path)
        self.server.error = (422, {"detail": [{"loc": ["body", "design", "top"], "msg": "Required"}]})
        with self.assertRaisesRegex(ApiError, "body.design.top: Required"):
            self.client.call("/runs", "POST", {})
        self.assertEqual(len(self.server.mutations), 1)

    def test_timeout_does_not_retry_mutation(self):
        """Uncertain POST results remain explicit and are never automatically replayed."""
        self.server.delay = 0.2
        with self.assertRaisesRegex(ApiError, "No mutation was retried"):
            self.client.call("/runs", "POST", PROJECT["run_defaults"], timeout=0.03)
        self.assertEqual(len(self.server.requests), 1)

    def test_verified_download_is_atomic(self):
        """Publish the file only after both declared byte count and SHA-256 agree."""
        self.target.write_bytes(b"existing")
        counts = []
        result = self.client.download(ARTIFACT, self.target, threading.Event(), counts.append)
        self.assertEqual(self.target.read_bytes(), WAVEFORM)
        self.assertEqual(result["sha256"], ARTIFACT["sha256"])
        self.assertEqual(counts[-1], len(WAVEFORM))
        self.assertEqual(len(list(self.target.parent.iterdir())), 1)

    def test_corrupt_hash_and_size_preserve_destination(self):
        """A forged or stale artifact cannot overwrite an existing user file."""
        self.target.write_bytes(b"existing")
        for artifact in ({**ARTIFACT, "sha256": "0" * 64}, {**ARTIFACT, "size": 1}, {**ARTIFACT, "sha256": None}, {**ARTIFACT, "is_directory": True}):
            with self.assertRaises(ApiError):
                self.client.download(artifact, self.target, threading.Event())
            self.assertEqual(self.target.read_bytes(), b"existing")
            self.assertEqual(len(list(self.target.parent.iterdir())), 1)

    def test_formal_download_endpoint_is_bounded_and_integrity_checked(self):
        """Accept the literal session download contract, never an arbitrary supplied URL."""
        endpoint = "/formal-sessions/" + "a" * 32 + "/download?path=formal_out%2Ftests%2Ftrace.vcd"
        self.client.download(dict(ARTIFACT, download_path=endpoint), self.target, threading.Event())
        self.assertEqual(self.target.read_bytes(), WAVEFORM)
        self.assertTrue(self.server.requests[-1][1].endswith(endpoint))
        for invalid in ("https://evil.invalid/secret", "//evil.invalid/secret", endpoint + "&extra=1", "/artifacts/x/download"):
            with self.subTest(endpoint=invalid), self.assertRaises(ApiError):
                self.client.download(dict(ARTIFACT, download_path=invalid), self.target, threading.Event())
        self.assertEqual(self.target.read_bytes(), WAVEFORM)

    def test_cancel_does_not_publish(self):
        """Cooperative local cancellation keeps existing outputs intact and removes staging files."""
        self.target.write_bytes(b"existing")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.client.download(ARTIFACT, self.target, cancel)
        self.assertEqual(self.target.read_bytes(), b"existing")
        self.assertEqual(len(list(self.target.parent.iterdir())), 1)

    def test_sse_cursor_and_duplicates(self):
        """Deliver only monotonically increasing verified events, including after reconnect."""
        self.server.events.insert(1, self.server.events[0])
        events = list(self.client.events("run-1", 0, threading.Event()))
        self.assertEqual([event["sequence"] for event in events], [1, 2])
        self.assertEqual([event["sequence"] for event in self.client.events("run-1", 1, threading.Event())], [2])
        self.assertIn("after=1", self.server.requests[-1][1])

    def test_malformed_sse_does_not_advance(self):
        """Reject invalid sequence types and report oversized or malformed event bodies."""
        for event in ({"sequence": True, "type": "bad"}, {"sequence": 3, "type": None}, {"sequence": 4, "type": "log", "message": "x" * 300000}):
            self.server.events = [event]
            with self.assertRaises(ApiError):
                list(self.client.events("run-1", 0, threading.Event()))

    def test_upload_is_bounded_and_uses_safe_basename(self):
        """Upload literal source bytes without submitting local directory paths or shell text."""
        source = self.target.parent / "input.sv"
        source.write_bytes(b"module demo; endmodule")
        result = self.client.upload(PROJECT["id"], [source])
        self.assertEqual(result["items"][0]["path"], ".ucagent/uploads/input.sv")
        raw = self.server.mutations[-1][2]
        self.assertIn(b'filename="input.sv"', raw)
        self.assertNotIn(str(source.parent).encode(), raw)
        for paths in ([], [source] * 17, [source, source]):
            with self.assertRaises(ApiError):
                self.client.upload(PROJECT["id"], paths)


if __name__ == "__main__":
    unittest.main()
