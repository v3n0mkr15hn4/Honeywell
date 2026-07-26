from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm.client import (
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMResponseFormatError,
    LLMTimeoutError,
    OllamaLLMClient,
)


class _Handler(BaseHTTPRequestHandler):
    mode = "success"
    request_body: dict[str, object] = {}

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).request_body = json.loads(self.rfile.read(length))
        if type(self).mode == "timeout":
            time.sleep(0.2)
        if type(self).mode == "http_error":
            self.send_response(500)
            body = b'{"error":"test failure"}'
        elif type(self).mode == "invalid_envelope":
            self.send_response(200)
            body = b'{"done":false}'
        elif type(self).mode == "empty":
            self.send_response(200)
            body = b'{"done":true,"response":"   "}'
        else:
            self.send_response(200)
            body = (
                b'{"done":true,"done_reason":"stop",'
                b'"response":"{\\"supply_air_temperature_setpoint\\":23.0,'
                b'\\"strategy\\":\\"test\\",\\"reason\\":\\"ok\\"}"}'
            )
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def log_message(self, _format: str, *args: object) -> None:
        return


class OllamaLLMClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _Handler.mode = "success"
        _Handler.request_body = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def client(self, response_timeout_s: float = 1.0) -> OllamaLLMClient:
        return OllamaLLMClient(
            model="test-model",
            base_url=self.base_url,
            connect_timeout_s=1.0,
            response_timeout_s=response_timeout_s,
        )

    def test_successful_query_is_non_streaming_json_transport(self) -> None:
        response = self.client().query("test prompt")

        self.assertIn("supply_air_temperature_setpoint", response)
        self.assertEqual(_Handler.request_body["model"], "test-model")
        self.assertEqual(_Handler.request_body["stream"], False)
        self.assertEqual(_Handler.request_body["think"], False)
        self.assertIsInstance(_Handler.request_body["format"], dict)
        self.assertEqual(
            _Handler.request_body["options"]["num_predict"],
            128,
        )

    def test_empty_response_is_rejected(self) -> None:
        _Handler.mode = "empty"
        with self.assertRaises(LLMEmptyResponseError):
            self.client().query("test")

    def test_invalid_envelope_is_rejected(self) -> None:
        _Handler.mode = "invalid_envelope"
        with self.assertRaises(LLMResponseFormatError):
            self.client().query("test")

    def test_http_error_is_connection_failure(self) -> None:
        _Handler.mode = "http_error"
        with self.assertRaises(LLMConnectionError):
            self.client().query("test")

    def test_response_timeout_is_typed(self) -> None:
        _Handler.mode = "timeout"
        with self.assertRaises(LLMTimeoutError):
            self.client(response_timeout_s=0.05).query("test")

    def test_connection_failure_is_typed(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()
        client = OllamaLLMClient(
            model="test-model",
            base_url=f"http://127.0.0.1:{closed_port}",
            connect_timeout_s=0.2,
            response_timeout_s=0.05,
        )
        with self.assertRaises((LLMConnectionError, LLMTimeoutError)):
            client.query("test")


if __name__ == "__main__":
    unittest.main()
