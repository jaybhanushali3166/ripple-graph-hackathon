"""GraphClient connection settings: username, TLS and error mapping.

Unit tests need no database. The opt-in live check starts a throwaway TLS-only FalkorDB
with ACL users and a test CA (needs docker and openssl):
  RIPPLE_TLS_TEST=1 ~/.venvs/ripple-graph/bin/python -m unittest tests.graph.test_client -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "harbor"
sys.path.insert(0, str(REPO_ROOT))

try:
    from redis.exceptions import AuthenticationError, NoPermissionError

    from backend.app.graph.client import GraphClient
    from backend.app.graph.errors import GraphError, GraphUnavailable
    from backend.app.graph.repository import GraphRepository
    IMPORT_ERROR = None
except ImportError as exc:
    IMPORT_ERROR = exc

CONNECTION_ENV = ("FALKORDB_HOST", "FALKORDB_PORT", "FALKORDB_USERNAME", "FALKORDB_PASSWORD",
                  "FALKORDB_TLS", "FALKORDB_TLS_CA_CERTS", "RIPPLE_GRAPH_NAME")


def clean_env(**values):
    """Patch os.environ with only these connection variables set."""
    env = {k: v for k, v in os.environ.items() if k not in CONNECTION_ENV}
    env.update(values)
    return mock.patch.dict(os.environ, env, clear=True)


@unittest.skipIf(IMPORT_ERROR, "falkordb client not importable (%s)" % IMPORT_ERROR)
class ConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.ca_file = tempfile.NamedTemporaryFile(suffix=".crt", delete=False)
        self.ca_file.close()
        self.addCleanup(os.unlink, self.ca_file.name)

    def options(self, client):
        with mock.patch("backend.app.graph.client.FalkorDB") as falkordb:
            client._graph()
        return falkordb.call_args.kwargs

    def test_defaults_are_plaintext_without_username(self):
        with clean_env():
            options = self.options(GraphClient())
        self.assertEqual(options, {"host": "localhost", "port": 6379, "username": None, "password": None,
                                   "socket_timeout": 5.0, "socket_connect_timeout": 5.0})

    def test_environment_enables_username_and_verified_tls(self):
        with clean_env(FALKORDB_HOST="db.example.cloud", FALKORDB_PORT="6380", FALKORDB_USERNAME="ripple",
                       FALKORDB_PASSWORD="pw", FALKORDB_TLS="true", FALKORDB_TLS_CA_CERTS=self.ca_file.name):
            options = self.options(GraphClient())
        self.assertEqual(options, {"host": "db.example.cloud", "port": 6380, "username": "ripple", "password": "pw",
                                   "socket_timeout": 5.0, "socket_connect_timeout": 5.0, "ssl": True,
                                   "ssl_cert_reqs": "required", "ssl_check_hostname": True,
                                   "ssl_ca_certs": self.ca_file.name})

    def test_tls_without_ca_file_uses_the_system_store(self):
        with clean_env(FALKORDB_TLS="1"):
            options = self.options(GraphClient())
        self.assertIs(options["ssl"], True)
        self.assertIsNone(options["ssl_ca_certs"])
        self.assertIs(options["ssl_check_hostname"], True)

    def test_arguments_override_the_environment(self):
        with clean_env(FALKORDB_USERNAME="env_user", FALKORDB_TLS="true"):
            options = self.options(GraphClient(username="arg_user", tls=False))
        self.assertEqual(options["username"], "arg_user")
        self.assertNotIn("ssl", options)

    def test_tls_flag_is_strict(self):
        for value, expected in (("TRUE", True), (" yes ", True), ("on", True), ("0", False),
                                ("off", False), ("", False)):
            with self.subTest(value=value), clean_env(FALKORDB_TLS=value):
                self.assertIs(GraphClient().tls, expected)
        for typo in ("ture", "enabled", "2"):
            with self.subTest(typo=typo), clean_env(FALKORDB_TLS=typo):
                with self.assertRaises(ValueError):
                    GraphClient()

    def test_ca_file_requires_tls_and_must_exist(self):
        with clean_env(FALKORDB_TLS_CA_CERTS=self.ca_file.name):
            with self.assertRaises(ValueError):
                GraphClient()
        with clean_env(FALKORDB_TLS="true", FALKORDB_TLS_CA_CERTS="/nonexistent/ca.crt"):
            with self.assertRaises(ValueError):
                GraphClient()

    def test_for_graph_keeps_every_connection_setting(self):
        with clean_env():
            base = GraphClient(host="h", port=7000, password="pw", graph_name="g", timeout_seconds=2.5,
                               username="u", tls=True, tls_ca_certs=self.ca_file.name)
            other = base.for_graph("g__staging_x")
        for attr in ("host", "port", "username", "password", "timeout_seconds", "tls", "tls_ca_certs"):
            self.assertEqual(getattr(other, attr), getattr(base, attr), attr)
        self.assertEqual(other.graph_name, "g__staging_x")

    def test_rejected_credentials_are_reported_without_the_password(self):
        with clean_env():
            client = GraphClient(username="u", password="s3cret-value")
        with self.assertRaises(GraphUnavailable) as caught:
            client._run(lambda: (_ for _ in ()).throw(AuthenticationError("invalid username-password pair")))
        self.assertEqual(caught.exception.message, "FalkorDB rejected the username/password")
        self.assertNotIn("s3cret-value", repr((caught.exception.message, caught.exception.details)))

    def test_missing_permission_is_a_graph_error(self):
        with clean_env():
            client = GraphClient()
        with self.assertRaises(GraphError) as caught:
            client._run(lambda: (_ for _ in ()).throw(NoPermissionError("NOPERM no permission for 'rename'")))
        self.assertNotIsInstance(caught.exception, GraphUnavailable)
        self.assertIn("lacks permission", caught.exception.message)


TLS_IMAGE = "falkordb/falkordb:v4.22.1"
TLS_CONTAINER = "ripple-falkordb-tls"
TLS_PORT = 6383
PASSWORD = "tls-test-" + uuid.uuid4().hex[:8]


def run(*args):
    return subprocess.run(list(args), capture_output=True, text=True, check=True)


@unittest.skipUnless(os.environ.get("RIPPLE_TLS_TEST") == "1" and shutil.which("docker") and shutil.which("openssl")
                     and not IMPORT_ERROR,
                     "set RIPPLE_TLS_TEST=1 (and have docker + openssl) to run the live TLS/ACL check")
class LiveTlsTests(unittest.TestCase):
    """A TLS-only server: plaintext disabled, `default` user off, `ripple` (all commands)
    and `limited` (everything except RENAME). The certificate names only DNS:localhost."""

    @classmethod
    def setUpClass(cls):
        cls.certs = Path(tempfile.mkdtemp())
        c = cls.certs
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=ripple-test-ca",
            "-keyout", str(c / "ca.key"), "-out", str(c / "ca.crt"))
        run("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
            "-keyout", str(c / "server.key"), "-out", str(c / "server.csr"))
        (c / "san.ext").write_text("subjectAltName=DNS:localhost\n")
        run("openssl", "x509", "-req", "-in", str(c / "server.csr"), "-CA", str(c / "ca.crt"), "-CAkey",
            str(c / "ca.key"), "-CAcreateserial", "-days", "1", "-extfile", str(c / "san.ext"),
            "-out", str(c / "server.crt"))
        os.chmod(c / "server.key", 0o644)  # readable by the container's server user
        subprocess.run(["docker", "rm", "-f", TLS_CONTAINER], capture_output=True)
        args = ("--port 0 --tls-port 6379 --tls-cert-file /tls/server.crt --tls-key-file /tls/server.key "
                "--tls-ca-cert-file /tls/ca.crt --tls-auth-clients no --user default off "
                "--user ripple on >%s ~* &* +@all --user limited on >%s ~* &* +@all -rename" % (PASSWORD, PASSWORD))
        run("docker", "run", "-d", "--name", TLS_CONTAINER, "-p", "%d:6379" % TLS_PORT,
            "-v", "%s:/tls:ro" % c, "-e", "REDIS_ARGS=" + args, TLS_IMAGE)
        cls.ca = str(c / "ca.crt")
        deadline = time.time() + 40
        while True:
            try:
                cls.client("ripple").ping()
                break
            except GraphUnavailable:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rm", "-f", TLS_CONTAINER], capture_output=True)
        shutil.rmtree(cls.certs, ignore_errors=True)

    @classmethod
    def client(cls, user, host="localhost", password=PASSWORD, tls=True, ca=None, graph="ripple_tls"):
        return GraphClient(host=host, port=TLS_PORT, password=password, graph_name=graph,
                           timeout_seconds=3.0, username=user, tls=tls, tls_ca_certs=ca or cls.ca)

    def test_seed_and_read_over_tls_with_a_username(self):
        repo = GraphRepository(self.client("ripple"))
        dataset_id = repo.seed_demo(FIXTURES)  # staging graph + RENAME, all over TLS
        self.assertEqual(repo.get_version(), "%s:0" % dataset_id)
        statuses = {i["commitment_id"]: i["status"] for i in repo.list_impacts(1792233000000)["impacts"]}
        self.assertEqual(len(statuses), 4)

    def test_wrong_password_is_reported_as_rejected_credentials(self):
        with self.assertRaises(GraphUnavailable) as caught:
            self.client("ripple", password="wrong").ping()
        self.assertEqual(caught.exception.message, "FalkorDB rejected the username/password")

    def test_plaintext_to_a_tls_port_fails(self):
        with self.assertRaises(GraphUnavailable):
            GraphClient(host="localhost", port=TLS_PORT, password=PASSWORD, username="ripple",
                        graph_name="ripple_tls", timeout_seconds=3.0, tls=False).ping()

    def test_untrusted_certificate_fails_without_the_ca(self):
        with clean_env():  # no FALKORDB_TLS_CA_CERTS: the system store does not trust the test CA
            client = GraphClient(host="localhost", port=TLS_PORT, password=PASSWORD, username="ripple",
                                 graph_name="ripple_tls", timeout_seconds=3.0, tls=True)
        with self.assertRaises(GraphUnavailable):
            client.ping()

    def test_hostname_must_match_the_certificate(self):
        """The certificate is trusted but names only localhost, so 127.0.0.1 must be refused."""
        with self.assertRaises(GraphUnavailable):
            self.client("ripple", host="127.0.0.1").ping()

    def test_user_without_rename_cannot_reseed_and_the_live_graph_survives(self):
        repo = GraphRepository(self.client("ripple", graph="ripple_tls_perm"))
        repo.seed_demo(FIXTURES)
        version = repo.get_version()
        limited = GraphRepository(self.client("limited", graph="ripple_tls_perm"))
        with self.assertRaises(GraphError) as caught:
            limited.seed_demo(FIXTURES)
        self.assertIn("lacks permission", caught.exception.message)
        self.assertEqual(repo.get_version(), version)


if __name__ == "__main__":
    unittest.main()
