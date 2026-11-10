"""WP7 / AC 8: the egress allowlist and the CONNECT-only proxy.

Live tests talk only to listeners this test opens on 127.0.0.1. The default allowlist (the real API
host) is exercised through ``allowed()`` only; no test ever dials a non-loopback address.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket

import pytest

from archstudy.egress import DEFAULT_ALLOWLIST, EgressProxy, allowed, parse_listen

API = ("api.anthropic.com", 443)


# -- allowed(): pure decision table ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("api.anthropic.com", 443, True),
        ("API.ANTHROPIC.COM", 443, True),
        ("Api.Anthropic.Com", 443, True),
        ("api.anthropic.com", 80, False),
        ("api.anthropic.com", 8443, False),
        ("api.anthropic.com", 0, False),
        ("api.anthropic.com", 65536, False),
        ("api.anthropic.com", -443, False),
        ("api.anthropic.com", True, False),
        ("api.anthropic.com", "443", False),
        ("api.anthropic.com", 443.0, False),
        ("api.anthropic.com.", 443, False),
        ("api.anthropic.com..", 443, False),
        (".api.anthropic.com", 443, False),
        ("api.anthropic.com.evil.com", 443, False),
        ("evil.com.api.anthropic.com", 443, False),
        ("xapi.anthropic.com", 443, False),
        ("api.anthropic.comx", 443, False),
        ("anthropic.com", 443, False),
        ("api.anthropic.com@evil.com", 443, False),
        ("evil.com@api.anthropic.com", 443, False),
        ("user:pw@api.anthropic.com", 443, False),
        ("api.anthropic.com:443", 443, False),
        ("api.anthropic.com/", 443, False),
        ("api.anthropic.com\\evil.com", 443, False),
        ("api.anthropic.com?x", 443, False),
        ("api.anthropic.com#x", 443, False),
        ("api.anthropic.com ", 443, False),
        (" api.anthropic.com", 443, False),
        ("api.anthropic.com\n", 443, False),
        ("api.anthropic.com\r\n", 443, False),
        ("api.anthropic.com\x00", 443, False),
        ("api.anthropic.com\t", 443, False),
        ("api.anthropic." + chr(0x441) + "om", 443, False),
        ("api.anthropic.com" + chr(0x2024) + "evil.com", 443, False),
        ("*.anthropic.com", 443, False),
        ("*", 443, False),
        ("api.*.com", 443, False),
        ("", 443, False),
        ("api_anthropic.com", 443, False),
        ("127.0.0.1", 443, False),
        ("::1", 443, False),
        ("[::1]", 443, False),
        ("0.0.0.0", 443, False),
        ("169.254.169.254", 443, False),
        ("2130706433", 443, False),
        ("0x7f000001", 443, False),
        ("127.1", 443, False),
        ("localhost", 443, False),
        (None, 443, False),
        (b"api.anthropic.com", 443, False),
    ],
)
def test_allowed_default_table(host, port, expected):
    assert allowed(host, port) is expected


def test_default_allowlist_is_exactly_the_api_host():
    assert DEFAULT_ALLOWLIST == frozenset({API})


def test_ip_literal_allowed_only_when_itself_in_the_allowlist():
    custom = frozenset({("127.0.0.1", 9000)})
    assert allowed("127.0.0.1", 9000, custom) is True
    assert allowed("127.0.0.1", 9001, custom) is False
    assert allowed("127.0.0.2", 9000, custom) is False
    assert allowed("127.1", 9000, custom) is False
    assert allowed("127.000.000.001", 9000, custom) is False
    assert allowed("2130706433", 9000, custom) is False
    assert allowed("::ffff:127.0.0.1", 9000, custom) is False
    v6 = frozenset({("::1", 9000)})
    assert allowed("::1", 9000, v6) is True
    assert allowed("0:0:0:0:0:0:0:1", 9000, v6) is True


def test_a_wildcard_entry_in_the_allowlist_never_matches():
    wild = frozenset({("*.anthropic.com", 443)})
    assert allowed("api.anthropic.com", 443, wild) is False
    assert allowed("*.anthropic.com", 443, wild) is False


def test_empty_allowlist_refuses_everything():
    assert allowed("api.anthropic.com", 443, frozenset()) is False


def test_parse_listen():
    assert parse_listen("0.0.0.0:3128") == ("0.0.0.0", 3128)
    assert parse_listen("127.0.0.1:0") == ("127.0.0.1", 0)
    for bad in ("3128", "host:", ":3128", "host:abc", "host:99999", "host:-1"):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_listen(bad)


# -- live loopback tests ---------------------------------------------------------------------------


class Listener:
    """A loopback TCP server that echoes and counts the connections it accepts."""

    def __init__(self) -> None:
        self.accepted = 0
        self.closed = 0
        self.port = 0
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_conn, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.accepted += 1
        try:
            while data := await reader.read(4096):
                writer.write(data)
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            self.closed += 1
            writer.close()

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _read_head(reader: asyncio.StreamReader) -> bytes:
    return await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)


async def _send(proxy_port: int, payload: bytes) -> bytes:
    """Send raw bytes to the proxy and return the response head."""
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    try:
        writer.write(payload)
        await writer.drain()
        return await _read_head(reader)
    finally:
        writer.close()


def _connect(host: str, port: int, extra: str = "") -> bytes:
    return f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n{extra}\r\n".encode("ascii")


async def _with_proxy(allowlist, body, **kwargs):
    proxy = EgressProxy(allowlist, **kwargs)
    port = await proxy.start("127.0.0.1", 0)
    try:
        return await body(port)
    finally:
        await proxy.stop()


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


def test_allowed_target_tunnels_bytes_both_ways():
    async def scenario():
        echo = Listener()
        await echo.start()

        async def body(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_connect("127.0.0.1", echo.port))
            await writer.drain()
            head = await _read_head(reader)
            assert head.startswith(b"HTTP/1.1 200 Connection Established")
            for chunk in (b"hello", b"x" * 100_000):
                writer.write(chunk)
                await writer.drain()
                got = await asyncio.wait_for(reader.readexactly(len(chunk)), 5)
                assert got == chunk
            writer.close()

        try:
            await _with_proxy({("127.0.0.1", echo.port)}, body)
            await asyncio.sleep(0.2)
            assert echo.accepted == 1
            assert echo.closed == 1  # closing the client side closes the upstream side
        finally:
            await echo.stop()

    run(scenario())


def test_disallowed_target_gets_403_and_no_connection_is_attempted():
    async def scenario():
        echo, decoy = Listener(), Listener()
        await echo.start()
        await decoy.start()

        async def body(port):
            head = await _send(port, _connect("127.0.0.1", decoy.port))
            assert head.startswith(b"HTTP/1.1 403")
            head = await _send(port, _connect("127.0.0.2", echo.port))
            assert head.startswith(b"HTTP/1.1 403")
            head = await _send(port, _connect("127.0.0.1@evil.example", echo.port))
            assert head.startswith(b"HTTP/1.1 403")
            head = await _send(port, _connect("*", echo.port))
            assert head.startswith(b"HTTP/1.1 403")

        try:
            await _with_proxy({("127.0.0.1", echo.port)}, body)
            await asyncio.sleep(0.3)
            assert decoy.accepted == 0, "the proxy dialed a target that is not on the allowlist"
            assert echo.accepted == 0, "denied requests must not touch even the allowed listener"
        finally:
            await echo.stop()
            await decoy.stop()

    run(scenario())


def test_hostname_resolving_to_a_private_address_is_refused():
    async def scenario():
        echo = Listener()
        await echo.start()

        async def body(port):
            head = await _send(port, _connect("localhost", echo.port))
            assert head.startswith(b"HTTP/1.1 403")

        try:
            await _with_proxy({("localhost", echo.port)}, body)
            await asyncio.sleep(0.2)
            assert echo.accepted == 0
        finally:
            await echo.stop()

    run(scenario())


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "connect", "TRACE"])
def test_non_connect_methods_get_405(method):
    async def scenario():
        echo = Listener()
        await echo.start()

        async def body(port):
            head = await _send(
                port, f"{method} http://127.0.0.1:{echo.port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode()
            )
            assert head.startswith(b"HTTP/1.1 405")
            assert b"Allow: CONNECT" in head

        try:
            await _with_proxy({("127.0.0.1", echo.port)}, body)
            await asyncio.sleep(0.1)
            assert echo.accepted == 0
        finally:
            await echo.stop()

    run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        b"garbage\r\n\r\n",
        b"CONNECT\r\n\r\n",
        b"CONNECT 127.0.0.1:1\r\n\r\n",
        b"CONNECT 127.0.0.1:1 HTTP/1.1 extra\r\n\r\n",
        b"CONNECT 127.0.0.1:1  HTTP/1.1\r\n\r\n",
        b"CONNECT 127.0.0.1:1 HTTP/2\r\n\r\n",
        b"CONNECT 127.0.0.1 HTTP/1.1\r\n\r\n",
        b"CONNECT 127.0.0.1:abc HTTP/1.1\r\n\r\n",
        b"CONNECT 127.0.0.1:99999999 HTTP/1.1\r\n\r\n",
        b"CONNECT \xff\xfe:1 HTTP/1.1\r\n\r\n",
        b"\r\n\r\n",
    ],
)
def test_malformed_request_gets_400(payload):
    async def scenario():
        async def body(port):
            head = await _send(port, payload)
            assert head.startswith(b"HTTP/1.1 400"), head

        await _with_proxy({("127.0.0.1", 1)}, body)

    run(scenario())


def test_oversized_header_gets_400_and_is_never_forwarded():
    async def scenario():
        echo = Listener()
        await echo.start()

        async def body(port):
            big = _connect("127.0.0.1", echo.port, "X-Pad: " + "a" * 9000 + "\r\n")
            head = await _send(port, big)
            assert head.startswith(b"HTTP/1.1 400")
            # No terminator at all and more than the cap: still 400, not a hang.
            head = await _send(port, b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nX: " + b"b" * 20000)
            assert head.startswith(b"HTTP/1.1 400")

        try:
            await _with_proxy({("127.0.0.1", echo.port)}, body)
            await asyncio.sleep(0.1)
            assert echo.accepted == 0
        finally:
            await echo.stop()

    run(scenario())


def test_slow_client_gets_408():
    async def scenario():
        async def body(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"CONNECT 127.0.0.1:1 HTTP/1.1\r\n")  # never finishes the headers
            await writer.drain()
            head = await _read_head(reader)
            assert head.startswith(b"HTTP/1.1 408")
            assert await asyncio.wait_for(reader.read(), 5) == b""  # connection closed
            writer.close()

        await _with_proxy({("127.0.0.1", 1)}, body, header_timeout=0.3)

    run(scenario())


def test_allowed_but_unreachable_target_gets_502():
    dead = _free_port()

    async def scenario():
        async def body(port):
            head = await _send(port, _connect("127.0.0.1", dead))
            assert head.startswith(b"HTTP/1.1 502")

        await _with_proxy({("127.0.0.1", dead)}, body, connect_timeout=2)

    run(scenario())


def test_idle_tunnel_is_closed():
    async def scenario():
        echo = Listener()
        await echo.start()

        async def body(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_connect("127.0.0.1", echo.port))
            await writer.drain()
            assert (await _read_head(reader)).startswith(b"HTTP/1.1 200")
            assert await asyncio.wait_for(reader.read(), 5) == b""  # closed by the idle timeout
            writer.close()

        try:
            await _with_proxy({("127.0.0.1", echo.port)}, body, idle_timeout=0.3)
            await asyncio.sleep(0.2)
            assert echo.closed == 1
        finally:
            await echo.stop()

    run(scenario())


def test_upstream_closing_closes_the_client_side():
    async def scenario():
        async def hang_up(reader, writer):
            writer.close()

        server = await asyncio.start_server(hang_up, "127.0.0.1", 0)
        up_port = server.sockets[0].getsockname()[1]

        async def body(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_connect("127.0.0.1", up_port))
            await writer.drain()
            assert (await _read_head(reader)).startswith(b"HTTP/1.1 200")
            assert await asyncio.wait_for(reader.read(), 5) == b""
            writer.close()

        try:
            await _with_proxy({("127.0.0.1", up_port)}, body)
        finally:
            server.close()
            await server.wait_closed()

    run(scenario())


def test_stop_closes_open_tunnels():
    async def scenario():
        echo = Listener()
        await echo.start()
        proxy = EgressProxy({("127.0.0.1", echo.port)})
        port = await proxy.start("127.0.0.1", 0)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(_connect("127.0.0.1", echo.port))
        await writer.drain()
        assert (await _read_head(reader)).startswith(b"HTTP/1.1 200")
        await asyncio.wait_for(proxy.stop(), 5)
        assert await asyncio.wait_for(reader.read(), 5) == b""
        writer.close()
        await echo.stop()

    run(scenario())


def test_only_the_request_line_is_logged(caplog):
    secret_header = "Proxy-Authorization: Basic c3VwZXJzZWNyZXQ="
    body_marker = "TOPSECRETBODY"

    async def scenario():
        echo = Listener()
        await echo.start()

        async def body(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_connect("127.0.0.1", echo.port, secret_header + "\r\n"))
            await writer.drain()
            assert (await _read_head(reader)).startswith(b"HTTP/1.1 200")
            writer.write(body_marker.encode())
            await writer.drain()
            await asyncio.wait_for(reader.readexactly(len(body_marker)), 5)
            writer.close()
            await _send(port, f"POST /x HTTP/1.1\r\n{secret_header}\r\n\r\n{body_marker}".encode())

        try:
            await _with_proxy({("127.0.0.1", echo.port)}, body)
            await asyncio.sleep(0.1)
        finally:
            await echo.stop()

    with caplog.at_level(logging.DEBUG, logger="archstudy.egress"):
        run(scenario())
    text = caplog.text
    assert "allow 127.0.0.1" in text and "deny method" in text
    assert body_marker not in text
    assert "c3VwZXJzZWNyZXQ" not in text and "Proxy-Authorization" not in text
