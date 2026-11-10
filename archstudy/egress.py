"""Egress allowlist: a CONNECT-only forward proxy that lets the agent container reach only the API host.

The agent container sits on an internal Docker network with no route out; this proxy is the only
thing it can talk to (via ``HTTPS_PROXY``). It speaks just enough HTTP to tunnel
``CONNECT host:port HTTP/1.1`` to an allowlisted ``(host, port)`` and refuses everything else.

Security properties:
  * the allowlist check happens before any connection to the target is attempted;
  * other methods get 405, a disallowed target 403, a malformed or oversized request 400, a slow one 408;
  * a hostname target must resolve to public addresses only, and the connection goes to the resolved
    address (no second lookup), so a poisoned name cannot point the tunnel at a private network;
  * only the request line is ever logged, never headers or tunneled bytes.

Run it with ``python -m archstudy.egress --listen 0.0.0.0:3128``.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import re
import socket
from collections.abc import Iterable

__all__ = ["DEFAULT_ALLOWLIST", "EgressProxy", "allowed", "parse_listen", "main"]

log = logging.getLogger("archstudy.egress")

DEFAULT_ALLOWLIST: frozenset[tuple[str, int]] = frozenset({("api.anthropic.com", 443)})

_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
MAX_HEADER_BYTES = 8192


def _normalise(host: str) -> str | None:
    """Return the canonical form of a host, or None when it is not a plain hostname or IP literal."""
    if not isinstance(host, str) or not host or not host.isascii():
        return None
    lowered = host.lower()
    try:
        return str(ipaddress.ip_address(lowered))
    except ValueError:
        pass
    # fullmatch (not match/$) so a trailing newline, dot, '@', '*', ':', '/' or space never passes.
    if len(lowered) > 253 or not _HOSTNAME.fullmatch(lowered):
        return None
    return lowered


def allowed(host: str, port: int, allowlist: Iterable[tuple[str, int]] = DEFAULT_ALLOWLIST) -> bool:
    """True only for an exact, case-insensitive host match on an exact port. Anything odd is refused."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return False
    canonical = _normalise(host)
    if canonical is None:
        return False
    for entry_host, entry_port in allowlist:
        if entry_port == port and _normalise(entry_host) == canonical:
            return True
    return False


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _response(code: int, reason: str, extra: str = "") -> bytes:
    return (f"HTTP/1.1 {code} {reason}\r\n{extra}Content-Length: 0\r\nConnection: close\r\n\r\n").encode(
        "ascii"
    )


class EgressProxy:
    """asyncio CONNECT-only forward proxy restricted to an allowlist of (host, port) pairs."""

    def __init__(
        self,
        allowlist: Iterable[tuple[str, int]] = DEFAULT_ALLOWLIST,
        *,
        header_timeout: float = 10.0,
        connect_timeout: float = 10.0,
        idle_timeout: float = 60.0,
        max_header_bytes: int = MAX_HEADER_BYTES,
    ) -> None:
        self._allowlist = frozenset((str(h), int(p)) for h, p in allowlist)
        self._header_timeout = header_timeout
        self._connect_timeout = connect_timeout
        self._idle_timeout = idle_timeout
        self._max_header_bytes = max_header_bytes
        self._server: asyncio.base_events.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task] = set()

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        """Start listening; return the bound port."""
        self._server = await asyncio.start_server(self._handle, host, port)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Stop accepting, close every open tunnel and wait for the handlers to finish."""
        if self._server is None:
            return
        self._server.close()
        for writer in list(self._writers):
            writer.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._server.wait_closed()
        self._server = None

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("proxy not started")
        await self._server.serve_forever()

    # -- connection handling -------------------------------------------------------------------

    async def _read_head(self, reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
        """Read until the blank line; return (head, leftover). Raises ValueError when oversized."""
        buf = b""
        while True:
            end = buf.find(b"\r\n\r\n")
            if end != -1:
                if end + 4 > self._max_header_bytes:
                    raise ValueError("headers too large")
                return buf[:end], buf[end + 4 :]
            if len(buf) > self._max_header_bytes:
                raise ValueError("headers too large")
            chunk = await reader.read(4096)
            if not chunk:
                raise ValueError("connection closed before the end of the headers")
            buf += chunk

    async def _reply(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        try:
            writer.write(data)
            await writer.drain()
        except (ConnectionError, OSError):
            pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        self._writers.add(writer)
        try:
            await self._serve(reader, writer)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.warning("connection handler failed", exc_info=False)
        finally:
            self._writers.discard(writer)
            if task is not None:
                self._tasks.discard(task)
            writer.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head, leftover = await asyncio.wait_for(self._read_head(reader), self._header_timeout)
        except asyncio.TimeoutError:
            log.info("timeout waiting for request headers")
            await self._reply(writer, _response(408, "Request Timeout"))
            return
        except (ValueError, ConnectionError, OSError):
            log.info("bad request: oversized or truncated headers")
            await self._reply(writer, _response(400, "Bad Request"))
            return
        request_line = head.split(b"\r\n", 1)[0]
        try:
            text = request_line.decode("ascii")
        except UnicodeDecodeError:
            await self._reply(writer, _response(400, "Bad Request"))
            return
        parts = text.split(" ")
        if len(parts) != 3 or parts[2] != "HTTP/1.1" or not parts[0] or not parts[1]:
            log.info("bad request line: %r", text[:80])
            await self._reply(writer, _response(400, "Bad Request"))
            return
        method, target, _version = parts
        if method != "CONNECT":
            log.info("deny method %r", method[:16])
            await self._reply(writer, _response(405, "Method Not Allowed", "Allow: CONNECT\r\n"))
            return
        host, sep, port_text = target.rpartition(":")
        if not sep or not port_text.isascii() or not port_text.isdigit() or len(port_text) > 5:
            log.info("bad CONNECT target: %r", target[:80])
            await self._reply(writer, _response(400, "Bad Request"))
            return
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        port = int(port_text)
        if not allowed(host, port, self._allowlist):
            log.info("deny %r:%d", host[:80], port)
            await self._reply(writer, _response(403, "Forbidden"))
            return
        await self._tunnel(reader, writer, host.lower(), port, leftover)

    async def _resolve(self, host: str, port: int) -> str | None:
        """Pick the address to dial. IP literals are dialed as given; names must resolve publicly."""
        if _is_ip_literal(host):
            return host
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [str(info[4][0]) for info in infos]
        if not addresses or not all(_is_public(a) for a in addresses):
            return ""
        return addresses[0]

    async def _tunnel(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        host: str,
        port: int,
        leftover: bytes,
    ) -> None:
        try:
            address = await asyncio.wait_for(self._resolve(host, port), self._connect_timeout)
        except (OSError, asyncio.TimeoutError):
            log.info("deny %s:%d (does not resolve)", host, port)
            await self._reply(writer, _response(502, "Bad Gateway"))
            return
        if not address:
            log.info("deny %s:%d (resolves to a non-public address)", host, port)
            await self._reply(writer, _response(403, "Forbidden"))
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), self._connect_timeout
            )
        except (OSError, asyncio.TimeoutError):
            log.info("allow %s:%d but the connection failed", host, port)
            await self._reply(writer, _response(502, "Bad Gateway"))
            return
        log.info("allow %s:%d", host, port)
        self._writers.add(up_writer)
        try:
            await self._reply(writer, b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if leftover:
                up_writer.write(leftover)
            await self._relay(reader, writer, up_reader, up_writer)
        finally:
            self._writers.discard(up_writer)
            up_writer.close()

    async def _pipe(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await asyncio.wait_for(src.read(65536), self._idle_timeout)
                if not data:
                    return
                dst.write(data)
                await dst.drain()
        except (asyncio.TimeoutError, ConnectionError, OSError):
            return

    async def _relay(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        up_reader: asyncio.StreamReader,
        up_writer: asyncio.StreamWriter,
    ) -> None:
        forward = asyncio.ensure_future(self._pipe(client_reader, up_writer))
        backward = asyncio.ensure_future(self._pipe(up_reader, client_writer))
        try:
            await asyncio.wait({forward, backward}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for pipe in (forward, backward):
                pipe.cancel()
            await asyncio.gather(forward, backward, return_exceptions=True)
            client_writer.close()
            up_writer.close()


def parse_listen(value: str) -> tuple[str, int]:
    """Parse HOST:PORT for --listen."""
    host, sep, port_text = value.rpartition(":")
    if not sep or not host or not port_text.isdigit() or not 0 <= int(port_text) <= 65535:
        raise argparse.ArgumentTypeError(f"expected HOST:PORT, got {value!r}")
    return host, int(port_text)


async def _run(host: str, port: int) -> None:
    proxy = EgressProxy()
    bound = await proxy.start(host, port)
    log.info("egress proxy listening on %s:%d, allowlist %s", host, bound, sorted(DEFAULT_ALLOWLIST))
    try:
        await proxy.serve_forever()
    finally:
        await proxy.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m archstudy.egress", description=__doc__.split("\n")[0])
    parser.add_argument("--listen", type=parse_listen, default=("0.0.0.0", 3128), metavar="HOST:PORT")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(_run(*args.listen))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
