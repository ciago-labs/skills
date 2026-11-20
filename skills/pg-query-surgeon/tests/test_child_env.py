import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common  # noqa: E402


class TestChildEnv(unittest.TestCase):
    def test_unrelated_secrets_are_not_inherited(self):
        fake = {
            "PATH": "/usr/bin",
            "PGHOST": "db.internal",
            "LC_ALL": "C",
            "AWS_SECRET_ACCESS_KEY": "do-not-leak",
            "GITHUB_TOKEN": "do-not-leak",
        }
        with mock.patch.dict(os.environ, fake, clear=True):
            env = common.build_child_env()
        self.assertEqual(env["PGHOST"], "db.internal")
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["LC_ALL"], "C")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)


if __name__ == "__main__":
    unittest.main()
