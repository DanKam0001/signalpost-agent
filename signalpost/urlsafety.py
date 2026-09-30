"""Outbound URL policy for company-owned sources.

Only http/https, no credentials, default ports only, and the host must resolve exclusively to
public addresses (no private, loopback, link-local/metadata, multicast or reserved ranges). The
fetcher re-applies this check on every redirect hop.

For tests only, `SIGNALPOST_ALLOW_PRIVATE_HOSTS` may list hosts (`127.0.0.1`) or host:port pairs
(`127.0.0.1:8801`) that are exempt; every other private address stays refused. There is no global
off switch.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.parse import urlsplit

_BLOCKED_NAMES = ("localhost", "localhost.localdomain")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
_SHARED_SPACE = ipaddress.ip_network("100.64.0.0/10")
_DNS_TIMEOUT = 5.0
_DNS_TTL = 300.0


class UrlRefused(Exception):
    """Raised when a URL violates the outbound policy."""


def _address_is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.version == 4 and ip in _SHARED_SPACE:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


ALLOW_ENV = "SIGNALPOST_ALLOW_PRIVATE_HOSTS"


def allow_list_from_env() -> frozenset[str]:
    raw = os.environ.get(ALLOW_ENV, "")
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


class UrlPolicy:
    def __init__(self, allow_hosts: frozenset[str] | None = None):
        self.allow_hosts = allow_list_from_env() if allow_hosts is None else allow_hosts
        self._cache: dict[str, tuple[float, list[str]]] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dns")

    def _resolve(self, host: str) -> list[str]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(host)
            if hit and now - hit[0] < _DNS_TTL:
                return hit[1]
        future = self._pool.submit(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM)
        try:
            infos = future.result(timeout=_DNS_TIMEOUT)
        except FutureTimeout as exc:
            raise UrlRefused(f"dns_timeout: {host}") from exc
        except OSError as exc:
            raise UrlRefused(f"dns_failure: {host}") from exc
        addresses = sorted({info[4][0] for info in infos})
        with self._lock:
            self._cache[host] = (now, addresses)
        return addresses

    def check(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise UrlRefused(f"scheme_not_allowed: {parts.scheme or 'none'}")
        if parts.username or parts.password:
            raise UrlRefused("credentials_in_url")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise UrlRefused("missing_host")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if host in self.allow_hosts or f"{host}:{port}" in self.allow_hosts:
            return
        if parts.port not in (None, 80, 443):
            raise UrlRefused(f"port_not_allowed: {parts.port}")
        if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
            raise UrlRefused(f"host_not_allowed: {host}")
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            addresses = self._resolve(host)
        if not addresses:
            raise UrlRefused(f"dns_failure: {host}")
        for address in addresses:
            if not _address_is_public(address):
                raise UrlRefused(f"non_public_address: {host}")
