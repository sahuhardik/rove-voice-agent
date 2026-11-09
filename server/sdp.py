"""Making the answer's ICE candidates reachable from outside the host.

A server on a cloud instance with a public address is behind **1:1 NAT**: the
interface holds a private address, and the provider maps a public one onto it.
`aiortc` gathers host candidates from the interface, so the answer it produces
advertises the private address — which a browser anywhere else cannot reach,
and the session fails at ICE with no error that points at the cause.

The fix is the standard one for this topology: advertise the public address for
the same port. Nothing else about the candidate changes, because with 1:1 NAT
nothing else about it *is* different — the port mapping is identity.

The original candidate is kept as well as the rewritten one, so a session
started from the host itself still connects over the private address. ICE
checks every pair; adding a candidate cannot break a path that already worked.

Server reflexive (`typ srflx`) and relay candidates already carry a routable
address and are left alone.
"""

from __future__ import annotations

import re

#: ``a=candidate:<foundation> <component> <transport> <priority> <ip> <port> typ <type> ...``
_CANDIDATE_RE = re.compile(
    r"^a=candidate:(?P<foundation>\S+) (?P<component>\d+) (?P<transport>\S+) "
    r"(?P<priority>\d+) (?P<ip>\S+) (?P<port>\d+) typ (?P<type>\S+)(?P<rest>.*)$"
)

#: Only IPv4 literals are rewritten: the 1:1 NAT case this exists for is IPv4.
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def rewrite_host_candidates(sdp: str, public_ip: str) -> str:
    """Add a public-address copy of every IPv4 ``typ host`` candidate.

    Args:
        sdp: The SDP answer as `aiortc` produced it.
        public_ip: The address to advertise. Empty disables the rewrite.

    Returns:
        The SDP with an extra candidate line after each rewritten one. Line
        endings are preserved as they were found.
    """
    if not public_ip or not sdp:
        return sdp
    newline = "\r\n" if "\r\n" in sdp else "\n"
    out: list[str] = []
    for line in sdp.split(newline):
        out.append(line)
        match = _CANDIDATE_RE.match(line.strip())
        if not match or match.group("type") != "host":
            continue
        address = match.group("ip")
        if not _IPV4_RE.match(address) or address == public_ip:
            continue
        # A distinct foundation, because two candidates that differ in address
        # are two candidates: sharing a foundation would tell the peer they
        # share a path, and they do not.
        foundation = match.group("foundation") + "1"
        out.append(
            f"a=candidate:{foundation} {match.group('component')} "
            f"{match.group('transport')} {match.group('priority')} "
            f"{public_ip} {match.group('port')} typ host{match.group('rest')}"
        )
    return newline.join(out)


def candidate_addresses(sdp: str) -> list[str]:
    """Every address advertised in the SDP's candidates, in order.

    Used by `server/test_server.py` and by `server/verify.py`'s output, where
    the thing worth seeing is which addresses a peer was actually offered.
    """
    found: list[str] = []
    for line in sdp.replace("\r\n", "\n").split("\n"):
        match = _CANDIDATE_RE.match(line.strip())
        if match:
            found.append(match.group("ip"))
    return found
