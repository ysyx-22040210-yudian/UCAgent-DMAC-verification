"""Python 3.8 contracts for the offline service supervisor and in-memory credentials."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ucagent_tk.local_service import LocalService


class LocalServiceTests(unittest.TestCase):
    """Exercise startup identity, environment isolation, cleanup and platform boundaries."""

    def setUp(self):
        """Create isolated supervisor state without launching an EDA process."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = LocalService.__new__(LocalService)
        self.service.bundle = self.service.data = Path(self.temp.name)
        self.service.python = self.service.bundle / "bin/python"
        self.service.ready = self.service.data / "ready-test.json"
        self.service.token = "test-only-ephemeral-auth-token-value"
        self.service.process = self.service.log = self.service.client = None
        self.service.toolchains = None
        self.process = Mock(pid=98765)
        self.process.poll.return_value = None

    def launch(self, command, **kwargs):
        """Publish only a PID and loopback origin as the real child would do."""
        self.service.ready.write_text(json.dumps({"pid": 98765, "origin": "http://127.0.0.1:23456"}))
        self.command, self.environment = command, kwargs["env"]
        return self.process

    def test_start_is_authenticated_and_sanitized(self):
        """Keep secrets in memory and discard ambient Python/loader/license overrides."""
        with patch.dict(os.environ, {"PYTHONPATH": "bad", "LD_LIBRARY_PATH": "bad", "LM_LICENSE_FILE": "test-secret", "UCAGENT_PLATFORM_PASSWORD": "test-secret"}), patch("ucagent_tk.local_service.subprocess.Popen", side_effect=self.launch), patch("ucagent_tk.local_service.ApiClient") as client:
            self.assertIs(self.service.start(), client.return_value)
            client.assert_called_once_with("http://127.0.0.1:23456", token=self.service.token)
            for name in ("LD_LIBRARY_PATH", "LM_LICENSE_FILE", "UCAGENT_PLATFORM_PASSWORD"):
                self.assertNotIn(name, self.environment)
            self.assertNotEqual(self.environment["PYTHONPATH"], "bad")
            self.assertNotIn(self.service.token, " ".join(self.command))
            self.assertFalse(self.service.ready.exists())
            with self.assertRaises(RuntimeError):
                self.service.start()
            self.service.close()
            self.process.terminate.assert_called_once()
            self.assertIsNone(self.service.token)
            self.assertNotIn(b"test-only-ephemeral", (self.service.data / "service.log").read_bytes())

    def test_readiness_must_match_owned_child(self):
        """Do not attach to a stale or forged readiness PID."""
        with patch("ucagent_tk.local_service.subprocess.Popen", side_effect=self.launch), patch("ucagent_tk.local_service.json.loads", return_value={"pid": 99, "origin": "http://127.0.0.1:23456"}), patch("ucagent_tk.local_service.ApiClient") as client:
            with self.assertRaisesRegex(RuntimeError, "identity"):
                self.service.start()
            client.assert_not_called()
            self.assertTrue(self.service.log.closed)
            self.assertFalse(self.service.ready.exists())

    def test_host_profiles_admit_only_synopsys_license_names_in_memory(self):
        """A selected host profile permits VCF licensing without forwarding loader overrides."""
        self.service.toolchains = self.service.data / "host-toolchains.yaml"
        with patch.dict(os.environ, {"SNPSLMD_LICENSE_FILE": "test-only-license", "OTHER_LICENSE_FILE": "unrelated", "LD_PRELOAD": "untrusted"}), patch("ucagent_tk.local_service.subprocess.Popen", side_effect=self.launch), patch("ucagent_tk.local_service.ApiClient"):
            self.service.start()
            self.assertEqual(self.environment["SNPSLMD_LICENSE_FILE"], "test-only-license")
            self.assertNotIn("OTHER_LICENSE_FILE", self.environment)
            self.assertNotIn("LD_PRELOAD", self.environment)
            self.assertEqual(self.command[-2:], ["--toolchains", str(self.service.toolchains)])
            self.assertNotIn("test-only-license", " ".join(self.command))
            self.service.close()

    def test_readiness_never_forwards_token_off_host(self):
        """Reject even an otherwise valid HTTPS origin in local readiness data."""
        with patch("ucagent_tk.local_service.subprocess.Popen", side_effect=self.launch), patch("ucagent_tk.local_service.json.loads", return_value={"pid": 98765, "origin": "https://eda.example"}), patch("ucagent_tk.local_service.ApiClient") as client:
            with self.assertRaisesRegex(RuntimeError, "loopback"):
                self.service.start()
            client.assert_not_called()

    def test_startup_deadline_cleans_owned_child(self):
        """Bound startup and close its log even if the service never announces readiness."""
        with patch("ucagent_tk.local_service.subprocess.Popen", return_value=self.process), patch("ucagent_tk.local_service.time.monotonic", side_effect=[0, 26]):
            with self.assertRaises(TimeoutError):
                self.service.start()
        self.assertTrue(self.service.log.closed)
        self.process.terminate.assert_called_once()

    def test_root_and_unsupported_platforms_rejected(self):
        """Fail before modifying local data on unsupported hosts or root sessions."""
        with patch("ucagent_tk.local_service.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(ValueError, "Linux"):
                LocalService(self.service.bundle)
        with patch("ucagent_tk.local_service.platform.system", return_value="Linux"), patch("ucagent_tk.local_service.platform.machine", return_value="x86_64"), patch("ucagent_tk.local_service.os.geteuid", return_value=0, create=True):
            with self.assertRaisesRegex(ValueError, "ordinary user"):
                LocalService(self.service.bundle)
