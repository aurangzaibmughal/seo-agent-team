import asyncio
import socket
import ipaddress
import time
import hashlib
import hmac
import base64
import json
import os
from typing import Dict, Any, Optional, Tuple, List
from urllib.parse import urlparse, urljoin
import httpx
from cryptography.fernet import Fernet

from app.core.config import settings

_cipher = None

def get_cipher() -> Fernet:
    global _cipher
    if _cipher is not None:
        return _cipher

    key = settings.TOKEN_ENCRYPTION_KEY
    if not key:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError("Production mode requires TOKEN_ENCRYPTION_KEY environment variable to be set.")
        key_file = os.path.join(os.path.dirname(__file__), "..", "..", ".secret.key")
        if os.path.exists(key_file):
            with open(key_file, "rb") as f:
                key = f.read().decode().strip()
        else:
            new_key = Fernet.generate_key().decode()
            with open(key_file, "w") as f:
                f.write(new_key)
            key = new_key

    _cipher = Fernet(key.encode() if isinstance(key, str) else key)
    return _cipher

def encrypt_token(token: str) -> str:
    """Encrypts a token string. Tokens are never logged."""
    if not token:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypts an encrypted token string. Never logs the decrypted value."""
    if not encrypted_token:
        return ""
    cipher = get_cipher()
    return cipher.decrypt(encrypted_token.encode()).decode()

# Prohibited private/internal/cloud-metadata networks
PROHIBITED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),        # RFC-1918 Private
    ipaddress.ip_network("172.16.0.0/12"),     # RFC-1918 Private
    ipaddress.ip_network("192.168.0.0/16"),    # RFC-1918 Private
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / Cloud metadata (169.254.169.254)
    ipaddress.ip_network("100.64.0.0/10"),     # RFC-6598 Carrier-grade NAT (Shared Address Space)
    ipaddress.ip_network("0.0.0.0/8"),         # Current network
    ipaddress.ip_network("224.0.0.0/4"),       # Multicast
    ipaddress.ip_network("240.0.0.0/4"),       # Reserved
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped IPv6
    ipaddress.ip_network("::/128"),            # IPv6 unspecified
]

PROHIBITED_HOSTNAMES = {
    "localhost", "metadata", "instance-data", "metadata.google.internal"
}


class SSRFSecurityError(ValueError):
    """Raised when a URL targets a restricted/private network or violates security policy."""
    pass


def is_ip_prohibited(ip_str: str) -> bool:
    """Checks whether an IP address belongs to any prohibited private, link-local, CGNAT, or loopback range."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # Standard address properties
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True

        # Check IPv4-mapped IPv6 explicitly (e.g. ::ffff:127.0.0.1)
        if hasattr(ip, "ipv4_mapped") and ip.ipv4_mapped:
            if is_ip_prohibited(str(ip.ipv4_mapped)):
                return True

        # Explicit network CIDR checks
        for net in PROHIBITED_NETWORKS:
            if ip in net:
                return True
        return False
    except ValueError:
        return True


def parse_host_to_ip(hostname: str) -> Optional[ipaddress._BaseAddress]:
    """Attempts to parse hostname as standard IPv4/IPv6 or alternative numeric representations (integer, hex, octal)."""
    clean_host = hostname.strip().strip("[]").lower()

    # 1. Standard dotted-quad or IPv6
    try:
        return ipaddress.ip_address(clean_host)
    except ValueError:
        pass

    # 2. Alternative numeric formats: integer (2130706433), hex (0x7f000001), octal (017700000001)
    try:
        raw_bytes = socket.inet_aton(clean_host)
        # Ensure it was an actual numeric/hex address representation
        if clean_host.replace(".", "").isalnum():
            return ipaddress.IPv4Address(raw_bytes)
    except (OSError, ValueError):
        pass

    return None


def validate_safe_url(url: str, check_dns: bool = True) -> str:
    """Validates that a URL is safe from SSRF attacks.
    Rules:
    - Scheme must be http or https
    - URL must not contain userinfo credentials (@)
    - Port must be 80, 443, or unspecified
    - Hostname must not be localhost, *.localhost, *.internal, or metadata
    - Resolved IP and all A/AAAA records must not belong to prohibited CIDRs
    """
    if not url or not isinstance(url, str):
        raise SSRFSecurityError("URL cannot be empty")

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFSecurityError(f"Unsupported scheme '{scheme}'. Only http and https are allowed.")

    # Reject URLs containing userinfo (e.g. http://example.com@127.0.0.1/)
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise SSRFSecurityError("URLs containing userinfo (@) are prohibited")

    port = parsed.port
    if port is not None and port not in (80, 443):
        raise SSRFSecurityError(f"Prohibited port {port}. Only standard HTTP/HTTPS ports (80/443) are permitted.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise SSRFSecurityError("Missing hostname in URL")

    # Hostname suffix & pattern checks
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".internal")
        or hostname in PROHIBITED_HOSTNAMES
    ):
        raise SSRFSecurityError(f"Prohibited hostname '{hostname}'")

    # If hostname resolves to an IP directly (standard or numeric/hex/octal)
    ip_obj = parse_host_to_ip(hostname)
    if ip_obj is not None:
        if is_ip_prohibited(str(ip_obj)):
            raise SSRFSecurityError(f"Direct connection to private/internal IP {hostname} is blocked")
    elif check_dns:
        # Check EVERY A and AAAA record returned by DNS
        try:
            target_port = port or (443 if scheme == "https" else 80)
            addr_info = socket.getaddrinfo(hostname, target_port, proto=socket.IPPROTO_TCP)
            if not addr_info:
                raise SSRFSecurityError(f"DNS resolution failure for '{hostname}': no addresses found")
            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip = sockaddr[0]
                if is_ip_prohibited(ip):
                    raise SSRFSecurityError(f"Hostname '{hostname}' resolves to restricted IP {ip}")
        except socket.gaierror as e:
            raise SSRFSecurityError(f"DNS resolution failure for '{hostname}': {e}")

    return url.strip()


async def safe_fetch_url(
    client: httpx.AsyncClient,
    url: str,
    max_redirects: int = 5,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    timeout: float = 15.0
) -> httpx.Response:
    """Performs an HTTP request with strict hop-by-hop SSRF validation and connect-time peer verification (DNS rebinding guard)."""
    current_url = validate_safe_url(url)
    redirects_followed = 0

    while True:
        res = await client.get(current_url, follow_redirects=False, timeout=timeout)

        # Connect-time DNS rebinding verification: check actual TCP remote address
        if isinstance(getattr(res, "extensions", None), dict):
            stream = res.extensions.get("network_stream")
            if stream and hasattr(stream, "get_extra_info"):
                sock = stream.get_extra_info("socket")
                if sock and hasattr(sock, "getpeername"):
                    try:
                        peer_addr = sock.getpeername()
                        peer_ip = peer_addr[0] if isinstance(peer_addr, (tuple, list)) and len(peer_addr) >= 1 else None
                        if isinstance(peer_ip, str) and is_ip_prohibited(peer_ip):
                            if hasattr(res, "aclose"):
                                close_fn = res.aclose()
                                if asyncio.iscoroutine(close_fn):
                                    await close_fn
                            raise SSRFSecurityError(f"Connected socket resolved to prohibited IP {peer_ip} (DNS rebinding detected)")
                    except SSRFSecurityError:
                        raise
                    except Exception:
                        pass

        # Check response size cap
        content_len = res.headers.get("Content-Length")
        if content_len and int(content_len) > max_bytes:
            await res.aclose()
            raise SSRFSecurityError(f"Response size {content_len} bytes exceeds max cap of {max_bytes} bytes")

        is_redirect = getattr(res, "is_redirect", False)
        is_redirect_status = getattr(res, "status_code", 0) in (301, 302, 303, 307, 308)
        if isinstance(is_redirect, bool) and is_redirect and is_redirect_status:
            redirects_followed += 1
            if redirects_followed > max_redirects:
                if hasattr(res, "aclose"):
                    close_fn = res.aclose()
                    if asyncio.iscoroutine(close_fn):
                        await close_fn
                raise SSRFSecurityError(f"Exceeded max redirects cap ({max_redirects})")

            location = res.headers.get("Location")
            if not location:
                if hasattr(res, "aclose"):
                    close_fn = res.aclose()
                    if asyncio.iscoroutine(close_fn):
                        await close_fn
                raise SSRFSecurityError("Redirect missing Location header")

            # Resolve relative redirect
            next_url = urljoin(current_url, location)
            # CRITICAL: Re-check SSRF safety of destination before following!
            current_url = validate_safe_url(next_url)
        else:
            return res


# ==============================================================================
# Authentication & Session Security (Production Mode)
# ==============================================================================

def get_session_secret() -> str:
    return getattr(settings, "SESSION_SECRET", None) or os.environ.get("SESSION_SECRET") or "dev-insecure-session-secret-change-in-production-32b"


def hash_password(password: str) -> str:
    """Hashes a password with SHA-256 and salt."""
    salt = "seo_salt_v1_"
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies plain password against stored hash with timing attack resistance."""
    if not hashed_password:
        return False
    computed = hash_password(plain_password)
    return hmac.compare_digest(computed, hashed_password)


def create_session_token(payload: Dict[str, Any], expires_in_seconds: int = 86400 * 7) -> str:
    """Creates a signed tamper-proof session token."""
    payload_copy = dict(payload)
    payload_copy["exp"] = int(time.time()) + expires_in_seconds
    raw_json = json.dumps(payload_copy, separators=(",", ":"))
    b64_data = base64.urlsafe_b64encode(raw_json.encode("utf-8")).decode("utf-8").rstrip("=")

    secret = get_session_secret().encode("utf-8")
    sig = hmac.new(secret, b64_data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"


def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifies signature and expiration of session token. Returns payload or None."""
    if not token:
        return None
    token = token.strip().strip('"')
    if "." not in token:
        return None
    try:
        b64_data, sig = token.split(".", 1)
        sig = sig.strip('"')
        secret = get_session_secret().encode("utf-8")
        expected_sig = hmac.new(secret, b64_data.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None

        pad = "=" * (-len(b64_data) % 4)
        raw_json = base64.urlsafe_b64decode((b64_data + pad).encode("utf-8")).decode("utf-8")
        payload = json.loads(raw_json)
        if time.time() > payload.get("exp", 0):
            return None
        return payload
    except Exception:
        return None


# ==============================================================================
# Rate Limiting (In-Memory Sliding Window for Job Creation)
# ==============================================================================

class InMemoryRateLimiter:
    """Simple thread-safe in-memory sliding window rate limiter."""
    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.hits: Dict[str, List[float]] = {}

    def is_allowed(self, client_ip: str) -> Tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean expired hits
        history = self.hits.get(client_ip, [])
        valid_history = [t for t in history if t > cutoff]

        if len(valid_history) >= self.max_requests:
            retry_after = int(valid_history[0] + self.window_seconds - now) + 1
            return False, max(retry_after, 1)

        valid_history.append(now)
        self.hits[client_ip] = valid_history
        return True, 0

job_creation_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)
login_rate_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)


def get_client_ip(request: Any) -> str:
    """Extracts client IP, ignoring X-Forwarded-For unless peer socket is in TRUSTED_PROXIES."""
    peer_ip = "127.0.0.1"
    if hasattr(request, "client") and request.client and request.client.host:
        peer_ip = request.client.host

    trusted_raw = getattr(settings, "TRUSTED_PROXIES", None) or ""
    trusted_proxies = {p.strip() for p in trusted_raw.split(",") if p.strip()}

    if peer_ip in trusted_proxies:
        xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        if xff:
            # Client IP is the first entry in X-Forwarded-For chain
            ips = [i.strip() for i in xff.split(",") if i.strip()]
            if ips:
                return ips[0]

    return peer_ip
