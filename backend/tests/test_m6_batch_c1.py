import ast
from pathlib import Path
import socket
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app, startup_recovery
from app.core.config import settings
from app.core.security import (
    validate_safe_url,
    safe_fetch_url,
    SSRFSecurityError,
    hash_password,
    verify_password,
    create_session_token,
    verify_session_token,
    job_creation_limiter,
    login_rate_limiter,
    get_client_ip,
    is_ip_prohibited,
)

client = TestClient(app)


# ==============================================================================
# 1. SSRF Guard: One Test Per Case
# ==============================================================================

def test_ssrf_blocks_127_loopback_ipv4():
    """Verify 127.0.0.0/8 loopback is blocked."""
    for u in ["http://127.0.0.1", "http://127.0.0.1:80", "http://127.1.2.3"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_10_private_range():
    """Verify 10.0.0.0/8 RFC-1918 private subnet is blocked."""
    for u in ["http://10.0.0.1", "http://10.255.255.254"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_172_16_private_range():
    """Verify 172.16.0.0/12 RFC-1918 private subnet is blocked."""
    for u in ["http://172.16.0.1", "http://172.31.255.254"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_192_168_private_range():
    """Verify 192.168.0.0/16 RFC-1918 private subnet is blocked."""
    for u in ["http://192.168.0.1", "http://192.168.1.254"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_169_254_link_local_and_metadata():
    """Verify 169.254.0.0/16 link-local and AWS/GCP cloud metadata endpoints are blocked."""
    for u in ["http://169.254.169.254", "http://169.254.1.1"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_100_64_cgnat():
    """Verify 100.64.0.0/10 Carrier-grade NAT (Shared Address Space RFC-6598) is blocked."""
    for u in ["http://100.64.0.1", "http://100.127.255.254"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_0_0_0_0_current_network():
    """Verify 0.0.0.0/8 current network is blocked."""
    for u in ["http://0.0.0.0", "http://0.0.0.0:80"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_ipv6_loopback():
    """Verify IPv6 loopback ::1 is blocked."""
    for u in ["http://[::1]", "http://[::1]:80", "http://[::]"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_fe80_ipv6_link_local():
    """Verify fe80::/10 IPv6 link-local addresses are blocked."""
    for u in ["http://[fe80::1]", "http://[fe80::a00:27ff:fe8e:ba81]"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_fc00_ipv6_unique_local():
    """Verify fc00::/7 IPv6 unique local addresses (ULA) are blocked."""
    for u in ["http://[fc00::1]", "http://[fd12:3456:789a:1::1]"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_ipv4_mapped_ipv6():
    """Verify IPv4-mapped IPv6 addresses targeting private/loopback IPs are blocked."""
    for u in ["http://[::ffff:127.0.0.1]", "http://[::ffff:10.0.0.1]", "http://[::ffff:169.254.169.254]"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_numeric_host_integer():
    """Verify decimal integer host notation (e.g. 2130706433 -> 127.0.0.1) is blocked."""
    with pytest.raises(SSRFSecurityError):
        validate_safe_url("http://2130706433", check_dns=False)


def test_ssrf_blocks_numeric_host_hex():
    """Verify hex host notation (e.g. 0x7f000001 -> 127.0.0.1) is blocked."""
    with pytest.raises(SSRFSecurityError):
        validate_safe_url("http://0x7f000001", check_dns=False)


def test_ssrf_blocks_numeric_host_octal():
    """Verify octal host notation (e.g. 017700000001 or 0177.0.0.1 -> 127.0.0.1) is blocked."""
    for u in ["http://017700000001", "http://0177.0.0.1"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_localhost_exact():
    """Verify localhost hostname is blocked."""
    for u in ["http://localhost", "http://localhost:80", "http://localhost:8000"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_subdomain_localhost():
    """Verify *.localhost subdomains (e.g. app.localhost) are blocked."""
    for u in ["http://app.localhost", "http://sub.domain.localhost"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_internal_suffix():
    """Verify *.internal domains and metadata hostnames are blocked."""
    for u in ["http://corp.internal", "http://metadata.google.internal", "http://service.internal"]:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_blocks_userinfo_in_url():
    """Verify URLs containing userinfo (@) are blocked to prevent parser spoofing."""
    bad_userinfo = [
        "http://example.com@127.0.0.1/",
        "http://admin:secret@127.0.0.1/",
        "http://user:password@example.com/",
    ]
    for u in bad_userinfo:
        with pytest.raises(SSRFSecurityError):
            validate_safe_url(u, check_dns=False)


def test_ssrf_checks_every_dns_record_a_and_aaaa():
    """Verify DNS resolution checks EVERY A and AAAA record, blocking if ANY is restricted."""
    # Simulate DNS response with a public IP followed by a loopback IP
    mock_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
    ]
    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        with pytest.raises(SSRFSecurityError) as exc_info:
            validate_safe_url("http://dual-resolving-host.com", check_dns=True)
        assert "resolves to restricted IP 127.0.0.1" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ssrf_dns_rebinding_connect_time_guard():
    """Verify safe_fetch_url detects and aborts if socket connects to a restricted peer IP."""
    # Mock httpx response with a socket connected to loopback (DNS rebinding simulation)
    mock_socket = MagicMock()
    mock_socket.getpeername.return_value = ("127.0.0.1", 80)

    mock_stream = MagicMock()
    mock_stream.get_extra_info.side_effect = lambda key: mock_socket if key == "socket" else None

    mock_res = MagicMock()
    mock_res.extensions = {"network_stream": mock_stream}
    mock_res.headers = {}
    mock_res.is_redirect = False
    mock_res.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_res)

    mock_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        with pytest.raises(SSRFSecurityError) as exc_info:
            await safe_fetch_url(mock_client, "http://rebound-domain.com", timeout=5.0)

    assert "DNS rebinding detected" in str(exc_info.value)
    mock_res.aclose.assert_awaited_once()


def test_ssrf_allows_safe_public_urls():
    """Verify valid public HTTPS/HTTP URLs pass validation."""
    valid_urls = [
        "https://webspire-agency.vercel.app/",
        "https://webspire-agency.vercel.app/services",
        "https://example.com",
        "http://example.com",
    ]
    for u in valid_urls:
        res = validate_safe_url(u, check_dns=False)
        assert res.startswith("http")


# ==============================================================================
# 2. Static AST Test: Enforce safe_fetch_url Usage
# ==============================================================================

def test_static_crawler_uses_safe_fetch_url():
    """Statically verifies that crawler modules never use raw client.get/httpx.get outside safe_fetch_url."""
    base_app = Path(__file__).parent.parent / "app"
    crawler_files = [
        base_app / "crawler" / "engine.py",
        base_app / "crawler" / "competitor_crawler.py"
    ]
    violations = []

    for filepath in crawler_files:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(filepath))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("get", "post", "put", "delete", "patch"):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id in ("client", "httpx", "requests", "aiohttp"):
                            violations.append(f"{filepath}:{node.lineno}: {node.func.value.id}.{node.func.attr}")

    assert violations == [], f"Found direct HTTP calls in crawler bypassing safe_fetch_url: {violations}"


# ==============================================================================
# 3. Secure by Default & Authentication Tests
# ==============================================================================

def test_secure_by_default_requires_auth_when_not_development():
    """Verify auth is required when ENVIRONMENT is anything other than development or test."""
    for env_name in ["production", "staging", "secure_mode", ""]:
        with patch.object(settings, "ENVIRONMENT", env_name):
            res = client.get("/api/jobs/history")
            assert res.status_code == 401, f"Expected 401 for ENVIRONMENT='{env_name}', got {res.status_code}"


def test_development_mode_allows_unauthenticated_access():
    """Verify explicitly setting ENVIRONMENT='development' allows unauthenticated access."""
    with patch.object(settings, "ENVIRONMENT", "development"):
        res = client.get("/api/jobs/history")
        assert res.status_code == 200


def test_cookie_security_flags():
    """Verify session cookie has HttpOnly, SameSite=Lax, and Secure flags in non-dev environments."""
    raw_pass = "SuperSecureAdminPassword2026!"
    hashed_pass = hash_password(raw_pass)

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "APP_ADMIN_PASSWORD_HASH", hashed_pass), \
         patch.object(settings, "SESSION_SECRET", "super-secret-key-32-bytes-secure!!"):

        res_login = client.post("/api/auth/login", json={"password": raw_pass})
        assert res_login.status_code == 200
        set_cookie_header = res_login.headers.get("set-cookie", "").lower()

        assert "httponly" in set_cookie_header
        assert "samesite=lax" in set_cookie_header
        assert "secure" in set_cookie_header


def test_cors_rejects_wildcard_in_production():
    """Verify startup fails if wildcard CORS origin '*' is configured in production mode."""
    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch.object(settings, "APP_ADMIN_PASSWORD_HASH", "valid_hash"), \
         patch.object(settings, "SESSION_SECRET", "valid_secret_32_bytes_long_here"), \
         patch.object(settings, "TOKEN_ENCRYPTION_KEY", "valid_key"), \
         patch.object(settings, "CORS_ALLOWED_ORIGINS", "*"):

        with pytest.raises(RuntimeError) as exc_info:
            startup_recovery()
        assert "Wildcard '*' CORS origin is strictly forbidden in production mode" in str(exc_info.value)


def test_login_rate_limiting():
    """Verify exceeding 5 login attempts within a minute triggers HTTP 429."""
    test_ip = "198.51.100.99"
    login_rate_limiter.hits[test_ip] = []

    for _ in range(5):
        allowed, retry_after = login_rate_limiter.is_allowed(test_ip)
        assert allowed is True

    allowed, retry_after = login_rate_limiter.is_allowed(test_ip)
    assert allowed is False
    assert retry_after > 0


def test_x_forwarded_for_ignored_without_trusted_proxy():
    """Verify X-Forwarded-For is ignored when the peer socket is not in TRUSTED_PROXIES."""
    mock_request = MagicMock()
    mock_request.client.host = "192.168.1.100"  # Untrusted peer
    mock_request.headers = {"x-forwarded-for": "203.0.113.195"}

    with patch.object(settings, "TRUSTED_PROXIES", "10.0.0.1,10.0.0.2"):
        resolved_ip = get_client_ip(mock_request)
        assert resolved_ip == "192.168.1.100"  # Did NOT trust XFF header


def test_x_forwarded_for_respected_with_trusted_proxy():
    """Verify X-Forwarded-For is respected when the peer socket is in TRUSTED_PROXIES."""
    mock_request = MagicMock()
    mock_request.client.host = "10.0.0.1"  # In trusted proxies list
    mock_request.headers = {"x-forwarded-for": "203.0.113.195, 10.0.0.1"}

    with patch.object(settings, "TRUSTED_PROXIES", "10.0.0.1,10.0.0.2"):
        resolved_ip = get_client_ip(mock_request)
        assert resolved_ip == "203.0.113.195"  # Respected original client IP from XFF


def test_demo_mode_disabled_in_production():
    """Verify that is_demo=True is blocked in production environment."""
    with patch.object(settings, "ENVIRONMENT", "production"):
        token = create_session_token({"role": "admin"})
        res = client.post(
            "/api/jobs",
            json={"url": "https://webspire-agency.vercel.app/", "max_pages": 10, "is_demo": True},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 400
        assert "Demo mode seeding is disabled in production" in res.json()["detail"]


def test_healthz_endpoint():
    """Verify /healthz returns status ok and environment info."""
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "environment" in data
