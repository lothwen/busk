"""Network interfaces and addresses, for the output routes and the web remote.

:func:`ipv4_addresses` lists each interface's IPv4 address,
:func:`broadcast_address` reads an interface's directed broadcast address
and :func:`interface_network` its IPv4 network. They use ``ioctl`` requests
(``SIOCGIFADDR``, ``SIOCGIFBRDADDR``, ``SIOCGIFNETMASK``), the way ``ip
addr`` learns them, without parsing command output; they need Linux and
raise ``OSError`` elsewhere. The web remote prints one URL per address
(phase-6-plan §5.13). Art-Net broadcast routes send to the broadcast address
of their interface, and unicast only to the discovered nodes on its network
(§5.14).

:func:`interface_index` and :func:`resolve` work on any platform. sACN and
Art-Net routes share them, so both report an unknown interface or host in the
same words.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import sys
from typing import Final

SIOCGIFADDR: Final = 0x8915
"""``ioctl`` request: an interface's address (``linux/sockios.h``)."""

SIOCGIFBRDADDR: Final = 0x8919
"""``ioctl`` request: an interface's broadcast address (``linux/sockios.h``)."""

SIOCGIFNETMASK: Final = 0x891B
"""``ioctl`` request: an interface's network mask (``linux/sockios.h``)."""

_IFREQ: Final = struct.Struct("16s16s")
"""``struct ifreq``: the interface name, then a ``sockaddr_in`` (family,
port, address, padding)."""


def ipv4_addresses() -> list[tuple[str, str]]:
    """``(interface, address)`` for each interface with an IPv4 address, in
    interface index order (only an interface's primary address). Raises
    ``OSError`` on a system other than Linux."""
    if sys.platform != "linux":
        raise OSError("interface addresses are read with Linux ioctls")
    addresses = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in socket.if_nameindex():
            try:
                address = _ioctl_address(sock, name, SIOCGIFADDR)
            except OSError:  # no IPv4 address
                continue
            addresses.append((name, address))
    return addresses


def broadcast_address(iface: str) -> str:
    """The directed broadcast address of ``iface``: an interface name, or one
    of the IPv4 addresses :func:`ipv4_addresses` lists.

    Raises ``OSError`` with a message for the route's status when there is no
    such interface, when it has no broadcast address (the loopback), or on a
    system other than Linux.
    """
    if sys.platform != "linux":
        raise OSError("broadcast addresses are read with Linux ioctls")
    name = _interface_name(iface)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            address = _ioctl_address(sock, name, SIOCGIFBRDADDR)
        except OSError as exc:
            raise OSError(f"no broadcast address on {iface!r}: {exc.strerror}") from None
    if address == "0.0.0.0":
        raise OSError(f"no broadcast address on {iface!r}")
    return address


def interface_network(iface: str) -> ipaddress.IPv4Network:
    """The IPv4 network of ``iface`` (a name or one of its addresses), from
    its address and network mask: ``192.168.1.0/24`` for ``192.168.1.135``
    with mask ``255.255.255.0``. Raises ``OSError`` as
    :func:`broadcast_address` does."""
    if sys.platform != "linux":
        raise OSError("interface networks are read with Linux ioctls")
    name = _interface_name(iface)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            address = _ioctl_address(sock, name, SIOCGIFADDR)
            mask = _ioctl_address(sock, name, SIOCGIFNETMASK)
        except OSError as exc:
            raise OSError(f"no IPv4 address on {iface!r}: {exc.strerror}") from None
    return ipaddress.IPv4Interface(f"{address}/{mask}").network


def interface_index(name: str) -> int:
    """The index of the interface called ``name``; ``OSError`` naming the
    available interfaces if there is none."""
    try:
        return socket.if_nametoindex(name)
    except OSError:
        available = ", ".join(each for _, each in socket.if_nameindex())
        raise OSError(f"no network interface {name!r} (available: {available})") from None


def resolve(host: str) -> str:
    """The IPv4 address of ``host`` (a name or a literal)."""
    try:
        found = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        raise OSError(f"cannot resolve host {host!r}: {exc.strerror}") from None
    return str(found[0][4][0])


def _interface_name(iface: str) -> str:
    """The name of the interface ``iface`` names or has as an address."""
    try:
        ipaddress.IPv4Address(iface)
    except ValueError:
        interface_index(iface)  # the "no network interface" message
        return iface
    names = [each for each, address in ipv4_addresses() if address == iface]
    if not names:
        raise OSError(f"no network interface has the address {iface}") from None
    return names[0]


def _ioctl_address(sock: socket.socket, name: str, request: int) -> str:
    """The IPv4 address that the interface ``ioctl`` ``request`` returns for
    interface ``name`` (Linux only: the callers check)."""
    import fcntl  # Unix only: imported where it is used

    reply = fcntl.ioctl(sock.fileno(), request, _IFREQ.pack(name.encode()[:15], b""))
    return socket.inet_ntoa(reply[20:24])
