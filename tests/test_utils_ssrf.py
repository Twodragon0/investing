"""SSRF guard tests for is_private_url_target() in scripts/common/utils.py.

Test strategy
-------------
- Literal private IP URLs (IPv4 + IPv6)          -> must block
- Single-label hostnames                          -> must block
- Known rebinding domain suffixes                 -> must block
- DNS-resolved private IPs via mocked getaddrinfo -> must block  [RED until DNS check added]
- Public domains                                  -> must NOT block (false-positive guard)
- getaddrinfo failure                             -> fail-closed (must block)
- IPv6 link-local and IPv4-mapped IPv6            -> must block
- Hex/octal/decimal encoded IPs                   -> must block

Mocking conventions
-------------------
socket.getaddrinfo is always patched to prevent real network calls.
The cache on _resolve_hostname_ips (lru_cache) is cleared via autouse fixture.
"""

import ipaddress
import socket
from unittest.mock import patch

import pytest

from common.utils import is_private_url_target

# ---------------------------------------------------------------------------
# Autouse fixture: clear lru_cache on the DNS resolver if it exists
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_dns_cache():
    """Clear the DNS resolution cache before every test."""
    try:
        from common.utils import _resolve_hostname_ips

        _resolve_hostname_ips.cache_clear()
    except AttributeError:
        pass  # Cache not present yet (pre-implementation); no-op
    yield
    try:
        from common.utils import _resolve_hostname_ips

        _resolve_hostname_ips.cache_clear()
    except AttributeError:
        pass


# ---------------------------------------------------------------------------
# Helper: build a fake getaddrinfo return value for a given IP string
# ---------------------------------------------------------------------------


def _fake_getaddrinfo(ip_str):
    """Return a list mimicking socket.getaddrinfo() output for one IP."""
    ip = ipaddress.ip_address(ip_str)
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, "", (ip_str, 0))]


# ---------------------------------------------------------------------------
# 1. Literal private / loopback / link-local IPv4
# ---------------------------------------------------------------------------


class TestLiteralPrivateIPv4:
    def test_blocks_loopback_127(self):
        assert is_private_url_target("http://127.0.0.1/admin") is True

    def test_blocks_loopback_127_with_port(self):
        assert is_private_url_target("http://127.0.0.1:8080/secret") is True

    def test_blocks_class_a_private_10(self):
        assert is_private_url_target("http://10.0.0.1/internal") is True

    def test_blocks_class_b_private_172_16(self):
        assert is_private_url_target("http://172.16.0.1/api") is True

    def test_blocks_class_c_private_192_168(self):
        assert is_private_url_target("http://192.168.1.100/settings") is True

    def test_blocks_aws_metadata_169_254(self):
        assert is_private_url_target("http://169.254.169.254/latest/meta-data/") is True

    def test_blocks_unspecified_0_0_0_0(self):
        assert is_private_url_target("http://0.0.0.0/") is True


# ---------------------------------------------------------------------------
# 2. Literal private / loopback IPv6
# ---------------------------------------------------------------------------


class TestLiteralPrivateIPv6:
    def test_blocks_ipv6_loopback(self):
        assert is_private_url_target("http://[::1]/admin") is True

    def test_blocks_ipv6_link_local_fe80(self):
        assert is_private_url_target("http://[fe80::1]/internal") is True

    def test_blocks_ipv6_link_local_fe80_with_suffix(self):
        assert is_private_url_target("http://[fe80::dead:beef]/api") is True

    def test_blocks_ipv4_mapped_ipv6_loopback(self):
        # ::ffff:127.0.0.1 maps to 127.0.0.1
        assert is_private_url_target("http://[::ffff:127.0.0.1]/") is True

    def test_blocks_ipv4_mapped_ipv6_private(self):
        # ::ffff:10.0.0.1 maps to 10.0.0.1
        assert is_private_url_target("http://[::ffff:10.0.0.1]/") is True


# ---------------------------------------------------------------------------
# 3. Encoded IP representations
# ---------------------------------------------------------------------------


class TestEncodedIPs:
    def test_blocks_hex_encoded_loopback(self):
        # 0x7f000001 == 127.0.0.1 — Python's urlparse extracts this as hostname
        # urlparse("http://0x7f000001/") -> hostname == "0x7f000001"
        # ip_address() can parse hex integers
        assert is_private_url_target("http://0x7f000001/") is True

    def test_blocks_decimal_encoded_loopback(self):
        # 2130706433 == 127.0.0.1
        assert is_private_url_target("http://2130706433/") is True

    def test_octal_ip_resolved_to_private_via_dns_mock(self):
        # Platform note: Python's ipaddress module does NOT parse octal octets
        # (e.g. 0177.0.0.1 is not treated as 127.0.0.1).  macOS getaddrinfo
        # also resolves 0177.0.0.1 as 177.0.0.1 (decimal), which is public.
        # The guard catches this only when an attacker controls DNS and returns
        # a private IP.  We verify the DNS path: if getaddrinfo returns a
        # private IP for any hostname, it must be blocked.
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("127.0.0.1")):
            assert is_private_url_target("http://0177.0.0.1/") is True


# ---------------------------------------------------------------------------
# 4. Single-label hostnames (internal service discovery)
# ---------------------------------------------------------------------------


class TestSingleLabelHostnames:
    def test_blocks_redis(self):
        assert is_private_url_target("http://redis:6379/") is True

    def test_blocks_minio(self):
        assert is_private_url_target("http://minio/api/v1") is True

    def test_blocks_localhost_bare(self):
        assert is_private_url_target("http://localhost/") is True

    def test_blocks_db(self):
        assert is_private_url_target("http://db:5432/") is True


# ---------------------------------------------------------------------------
# 5. Private hostname literals and suffixes
# ---------------------------------------------------------------------------


class TestPrivateHostnamesAndSuffixes:
    def test_blocks_localhost_localdomain(self):
        assert is_private_url_target("http://localhost.localdomain/") is True

    def test_blocks_metadata_google_internal(self):
        assert is_private_url_target("https://metadata.google.internal/computeMetadata/v1/") is True

    def test_blocks_internal_suffix(self):
        assert is_private_url_target("https://api.corp.internal/secret") is True

    def test_blocks_local_suffix(self):
        assert is_private_url_target("https://printer.local/") is True

    def test_blocks_lan_suffix(self):
        assert is_private_url_target("https://nas.lan/") is True

    def test_blocks_localdomain_suffix(self):
        assert is_private_url_target("https://host.localdomain/path") is True


# ---------------------------------------------------------------------------
# 6. DNS-rebinding helper suffixes
# ---------------------------------------------------------------------------


class TestDnsRebindingSuffixes:
    def test_blocks_nip_io_private_ip(self):
        assert is_private_url_target("https://127-0-0-1.nip.io/") is True

    def test_blocks_nip_io_aws_metadata(self):
        assert is_private_url_target("https://169-254-169-254.nip.io/meta") is True

    def test_blocks_sslip_io(self):
        assert is_private_url_target("https://10.0.0.1.sslip.io/") is True

    def test_blocks_xip_io(self):
        assert is_private_url_target("https://192.168.1.1.xip.io/") is True

    def test_blocks_lvh_me(self):
        assert is_private_url_target("https://localhost.lvh.me/") is True

    def test_blocks_localtest_me(self):
        assert is_private_url_target("https://foo.localtest.me/") is True


# ---------------------------------------------------------------------------
# 7. DNS resolution check — RED until implementation adds getaddrinfo call
# ---------------------------------------------------------------------------


class TestDnsResolutionPrivateIp:
    """These tests mock socket.getaddrinfo to simulate an attacker domain
    whose A record resolves to a private/restricted IP.

    Expected: is_private_url_target() returns True (blocks).
    These tests will FAIL (RED) until the DNS-resolution logic is added
    to scripts/common/utils.py.
    """

    def test_blocks_domain_resolving_to_aws_metadata(self):
        """attacker.com A -> 169.254.169.254 should be blocked."""
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("169.254.169.254")):
            assert is_private_url_target("https://attacker.com/pwn") is True

    def test_blocks_domain_resolving_to_loopback(self):
        """evil.example A -> 127.0.0.1 should be blocked."""
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("127.0.0.1")):
            assert is_private_url_target("https://evil.example/admin") is True

    def test_blocks_domain_resolving_to_private_10_net(self):
        """corp-internal.evil A -> 10.10.10.10 should be blocked."""
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("10.10.10.10")):
            assert is_private_url_target("https://corp-internal.evil/data") is True

    def test_blocks_domain_resolving_to_link_local(self):
        """rebind.attacker.net A -> 169.254.0.1 (link-local) should be blocked."""
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("169.254.0.1")):
            assert is_private_url_target("https://rebind.attacker.net/") is True

    def test_blocks_domain_resolving_to_ipv6_loopback(self):
        """ipv6attack.com AAAA -> ::1 should be blocked."""
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("::1")):
            assert is_private_url_target("https://ipv6attack.com/") is True

    def test_blocks_domain_resolving_to_ipv6_link_local(self):
        """linklocal.evil AAAA -> fe80::1 should be blocked."""
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("fe80::1")):
            assert is_private_url_target("https://linklocal.evil/") is True

    def test_blocks_when_multiple_addrs_any_private(self):
        """If ANY resolved address is private, the URL must be blocked."""
        mixed = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=mixed):
            assert is_private_url_target("https://mixed.example.com/") is True


# ---------------------------------------------------------------------------
# 8. Fail-closed: getaddrinfo raises OSError
# ---------------------------------------------------------------------------


class TestDnsResolutionFailClosed:
    """When DNS resolution fails, the guard must fail-closed (return True)."""

    def test_fail_closed_on_oserror(self):
        with patch("socket.getaddrinfo", side_effect=OSError("NXDOMAIN")):
            assert is_private_url_target("https://nonexistent.example.com/") is True

    def test_fail_closed_on_socket_gaierror(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("resolution failed")):
            assert is_private_url_target("https://unknown.tld/path") is True

    def test_fail_closed_on_timeout(self):
        with patch("socket.getaddrinfo", side_effect=TimeoutError("timed out")):
            assert is_private_url_target("https://slow-dns.example/") is True


# ---------------------------------------------------------------------------
# 9. Public domains must pass (false-positive prevention)
# ---------------------------------------------------------------------------


class TestPublicDomainAllowed:
    """Public domains resolving to public IPs must NOT be blocked.

    These tests mock getaddrinfo to return a well-known public IP so the
    test is deterministic and never makes real network calls.
    """

    def test_allows_github_com(self):
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("140.82.114.4")):
            assert is_private_url_target("https://github.com/torvalds/linux") is False

    def test_allows_example_com(self):
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("93.184.216.34")):
            assert is_private_url_target("https://example.com/feed.rss") is False

    def test_allows_google_com(self):
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("142.250.185.46")):
            assert is_private_url_target("https://google.com/") is False

    def test_allows_news_google_com(self):
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("142.250.185.46")):
            assert is_private_url_target("https://news.google.com/rss/articles/CBMi") is False

    def test_allows_coindesk_com(self):
        with patch("socket.getaddrinfo", return_value=_fake_getaddrinfo("104.18.25.71")):
            assert is_private_url_target("https://www.coindesk.com/markets/2026/") is False


# ---------------------------------------------------------------------------
# 10. Edge cases: malformed URLs
# ---------------------------------------------------------------------------


class TestMalformedUrls:
    def test_empty_string_blocked(self):
        assert is_private_url_target("") is True

    def test_no_host_blocked(self):
        assert is_private_url_target("http:///path") is True

    def test_just_scheme_blocked(self):
        assert is_private_url_target("http://") is True
