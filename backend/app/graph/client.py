"""Thin FalkorDB wrapper. Reads use ro_query, writes use query, always parameterized.

Callers pass Cypher text that lives in code or backend/queries/*.cypher plus a
parameter dict; user input is never concatenated into Cypher.
"""
import os

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError, TimeoutError as RedisTimeoutError
from falkordb import FalkorDB

from .errors import GraphError, GraphUnavailable, NotFound


class GraphClient:
    def __init__(self, host=None, port=None, password=None, graph_name=None, timeout_seconds=5.0):
        self.host = host or os.environ.get("FALKORDB_HOST", "localhost")
        self.port = int(port or os.environ.get("FALKORDB_PORT", "6379"))
        self.password = password if password is not None else os.environ.get("FALKORDB_PASSWORD") or None
        self.graph_name = graph_name or os.environ.get("RIPPLE_GRAPH_NAME", "ripple_demo")
        self.timeout_seconds = timeout_seconds
        self._db = None

    def _graph(self):
        if self._db is None:
            self._db = FalkorDB(host=self.host, port=self.port, password=self.password,
                                socket_timeout=self.timeout_seconds,
                                socket_connect_timeout=self.timeout_seconds)
        return self._db.select_graph(self.graph_name)

    def _run(self, action):
        try:
            return action()
        except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
            raise GraphUnavailable("FalkorDB is unreachable", {"cause": type(exc).__name__}) from exc
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
        return GraphClient(self.host, self.port, self.password, graph_name, self.timeout_seconds)

    def move_to(self, graph_name):
        """Atomically rename this graph to graph_name, replacing any graph already there.

        One Redis RENAME: no fork (unlike GRAPH.COPY, which intermittently failed with
        "could not fork" in local test runs) and no moment where graph_name is missing.
        """
        def rename():
            self._graph()  # opens the connection
            self._db.connection.execute_command("RENAME", self.graph_name, graph_name)
        self._run(rename)
