"""Scope guard — the ethics axis from the Hat ADRs, enforced in code.

Every active tool resolves its target through here. A target that resolves to
an IP outside the engagement's allowlist is refused before the tool runs.
"""
from __future__ import annotations

import ipaddress
import socket


class ScopeError(Exception):
    """Raised when a target falls outside the engagement scope."""


def resolve(target: str) -> list[str]:
    """Return the IP address(es) a target maps to. IP literals pass through."""
    target = (target or "").strip()
    if not target:
        raise ScopeError("empty target")
    try:
        ipaddress.ip_address(target)
        return [target]
    except ValueError:
        pass
    # tolerate a URL slipping through: strip scheme / path / port
    host = target.split("://")[-1].split("/")[0].split(":")[0]
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ScopeError(f"cannot resolve '{target}': {exc}") from exc
    return sorted({info[4][0] for info in infos})


def check(target: str, allowed: list[str]) -> tuple[bool, str]:
    """Return (in_scope, human-readable detail) for `target` vs `allowed`.

    `allowed` entries may be IPs, CIDRs, or hostnames.
    """
    nets: list = []
    for entry in allowed:
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            for ip in resolve(entry):
                nets.append(ipaddress.ip_network(ip, strict=False))
    ips = resolve(target)
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if not any(addr in net for net in nets):
            return False, f"{target} -> {ip} is OUTSIDE scope {allowed}"
    return True, f"{target} -> {', '.join(ips)} within scope {allowed}"


def enforce(target: str, allowed: list[str]) -> str:
    """Raise ScopeError if `target` is out of scope; return the detail if ok."""
    ok, detail = check(target, allowed)
    if not ok:
        raise ScopeError(f"SCOPE VIOLATION — {detail}")
    return detail
