from localmind.admin.netinfo import detect_lan_urls


def test_private_ipv4_handling():
    addresses = {
        "lo": [
            ("127.0.0.1", "127.0.0.1"),
        ],
        "eth0": [
            ("192.168.1.25", "192.168.1.25"),
            ("10.0.0.8", "10.0.0.8"),
        ],
    }
    urls = detect_lan_urls(addresses)
    assert "http://192.168.1.25:8000" in urls
    assert "http://10.0.0.8:8000" in urls
    assert "http://127.0.0.1:8000" not in urls


def test_loopback_exclusion_and_duplication_removal():
    addresses = {
        "eth0": [
            ("192.168.1.10", "192.168.1.10"),
            ("192.168.1.10", "192.168.1.10"),
        ],
        "lo": [
            ("127.0.0.1", "127.0.0.1"),
        ],
    }
    urls = detect_lan_urls(addresses)
    assert urls == ["http://192.168.1.10:8000"]


def test_invalid_addresses_filtered():
    addresses = {
        "eth0": [
            ("0.0.0.0", "0.0.0.0"),
            ("169.254.10.1", "169.254.10.1"),
            ("224.0.0.1", "224.0.0.1"),
            ("fe80::1", "fe80::1"),
            ("172.16.0.4", "172.16.0.4"),
        ]
    }
    urls = detect_lan_urls(addresses)
    assert urls == ["http://172.16.0.4:8000"]


def test_no_network_interface_fallback():
    assert detect_lan_urls({}) == []
