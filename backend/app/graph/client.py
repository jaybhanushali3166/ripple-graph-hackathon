"""Thin FalkorDB wrapper. Reads use ro_query, writes use query, always parameterized.

Callers pass Cypher text that lives in code or backend/queries/*.cypher plus a
parameter dict; user input is never concatenated into Cypher.

Connection settings come from arguments, else from the environment:
  FALKORDB_HOST, FALKORDB_PORT, FALKORDB_USERNAME, FALKORDB_PASSWORD,
  FALKORDB_TLS (true/false), FALKORDB_TLS_CA_CERTS (CA bundle path, optional),
  RIPPLE_GRAPH_NAME.
With TLS on, the server certificate is verified against the system CA store (or
FALKORDB_TLS_CA_CERTS) and its hostname is always checked.
"""
import os

from redis.exceptions import AuthenticationError as RedisAuthenticationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import NoPermissionError
from redis.exceptions import ResponseError, TimeoutError as RedisTimeoutError
from falkordb import FalkorDB

from .errors import GraphError, GraphUnavailable, NotFound

_TRUE, _FALSE = ("1", "true", "yes", "on"), ("", "0", "false", "no", "off")


def _env_flag(name):
    """Strict boolean env var: a typo must not silently turn TLS off."""
    value = os.environ.get(name, "").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError("%s must be one of %s, got %r" % (name, "/".join(_TRUE + _FALSE[1:]), value))


class GraphClient:
    def __init__(self, host=None, port=None, password=None, graph_name=None, timeout_seconds=5.0,
                 username=None, tls=None, tls_ca_certs=None):
        self.host = host or os.environ.get("FALKORDB_HOST", "localhost")
        self.port = int(port or os.environ.get("FALKORDB_PORT", "6379"))
        self.username = username if username is not None else os.environ.get("FALKORDB_USERNAME") or None
        self.password = password if password is not None else os.environ.get("FALKORDB_PASSWORD") or None
        self.tls = tls if tls is not None else _env_flag("FALKORDB_TLS")
        self.tls_ca_certs = (tls_ca_certs if tls_ca_certs is not None
                             else os.environ.get("FALKORDB_TLS_CA_CERTS") or None)
        if self.tls_ca_certs and not self.tls:
            raise ValueError("FALKORDB_TLS_CA_CERTS is set but TLS is off; set FALKORDB_TLS=true")
        if self.tls_ca_certs and not os.path.isfile(self.tls_ca_certs):
            raise ValueError("FALKORDB_TLS_CA_CERTS file not found: %r" % self.tls_ca_certs)
        self.graph_name = graph_name or os.environ.get("RIPPLE_GRAPH_NAME", "ripple_demo")
        self.timeout_seconds = timeout_seconds
        self._db = None

    def _connection_options(self):
        options = {"host": self.host, "port": self.port, "username": self.username,
                   "password": self.password, "socket_timeout": self.timeout_seconds,
                   "socket_connect_timeout": self.timeout_seconds}
        if self.tls:
            options.update(ssl=True, ssl_cert_reqs="required", ssl_check_hostname=True,
                           ssl_ca_certs=self.tls_ca_certs)
        return options

    def _graph(self):
        if self._db is None:
            self._db = FalkorDB(**self._connection_options())
        return self._db.select_graph(self.graph_name)

    def _run(self, action):
        try:
            return action()
        except RedisAuthenticationError as exc:  # a ConnectionError subclass: check it first
            raise GraphUnavailable("FalkorDB rejected the username/password",
                                   {"cause": type(exc).__name__}) from exc
        except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
            raise GraphUnavailable("FalkorDB is unreachable", {"cause": type(exc).__name__}) from exc
        except NoPermissionError as exc:
            raise GraphError("FalkorDB user lacks permission: %s" % exc) from exc
        except ResponseError as exc:
            if "empty key" in str(exc):
                raise NotFound("graph %r does not exist; seed it first" % self.graph_name) from exc
            raise GraphError("graph query failed: %s" % exc) from exc

    def ping(self):
        """Raise GraphUnavailable if the server cannot be reached."""
        def check():
            self._graph()
            self._db.connection.ping()
        self._run(check)

    def read(self, cypher, params=None):
        """Read-only query; returns result rows as lists of primitives."""
        return self._run(lambda: self._graph().ro_query(cypher, params or {}).result_set)

    def write(self, cypher, params=None):
        """Mutating query; returns {rows, nodes_created, relationships_created}."""
        result = self._run(lambda: self._graph().query(cypher, params or {}))
        return {"rows": result.result_set, "nodes_created": result.nodes_created,
                "relationships_created": result.relationships_created}

    def delete_graph(self):
        """Remove the whole graph; a missing graph is fine."""
        try:
            self._run(lambda: self._graph().delete())
        except NotFound:
            pass

    def for_graph(self, graph_name):
        """A client for another graph on the same server and credentials."""
        return GraphClient(self.host, self.port, self.password, graph_name, self.timeout_seconds,
                           username=self.username, tls=self.tls, tls_ca_certs=self.tls_ca_certs)

    def move_to(self, graph_name):
        """Atomically rename this graph to graph_name, replacing any graph already there.

        One Redis RENAME: no fork (unlike GRAPH.COPY, which intermittently failed with
        "could not fork" in local test runs) and no moment where graph_name is missing.
        """
        def rename():
            self._graph()  # opens the connection
            self._db.connection.execute_command("RENAME", self.graph_name, graph_name)
        self._run(rename)
