from __future__ import annotations

import ipaddress
from typing import Any


def detect_lan_urls(ifaces: dict[str, Any] | None, port: int = 8000) -> list[str]:
    """Return private IPv4 LAN URLs for trusted local network access."""
    if not ifaces:
        return []

    urls: list[str] = []
    seen: set[str] = set()

    for addresses in ifaces.values():
        if not addresses:
            continue
        for entry in addresses:
            address_value = None
            if isinstance(entry, dict):
                address_value = entry.get("address")
            elif isinstance(entry, tuple):
                if len(entry) > 0:
                    address_value = entry[0]
            elif hasattr(entry, "address"):
                address_value = entry.address
            if not isinstance(address_value, str):
                continue
            try:
                ip_obj = ipaddress.ip_address(address_value)
            except ValueError:
                continue
            if ip_obj.version != 4:
                continue
            if ip_obj.is_loopback or ip_obj.is_unspecified or ip_obj.is_multicast or ip_obj.is_link_local:
                continue
            if not ip_obj.is_private:
                continue
            candidate = f"http://{ip_obj}:{port}"
            if candidate not in seen:
                urls.append(candidate)
                seen.add(candidate)
    return urls
