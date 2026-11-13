# Deployment & Operations Guide

> [!IMPORTANT]
> **Host Constraint**: This system is architected for local deployment (`localhost`). Do not deploy to public cloud instances without approval, and never commit or store API secrets in hosted/public repositories.

---

## 1. Quick Start (Localhost Batch Scripts)

The fastest way to launch the full platform locally is via the root batch scripts:

```powershell
# In terminal 1 (FastAPI backend on port 8000)
.\start-backend.bat

# In terminal 2 (Next.js frontend on port 3000)
.\start-frontend.bat
```

Once running:
- **Frontend Dashboard**: [http://localhost:3000](http://localhost:3000)
- **Backend API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Healthcheck Endpoint**: [http://localhost:8000/healthz](http://localhost:8000/healthz)

---

## 2. Containerized Deployment (Docker Compose)

For multi-container orchestration with non-root security isolation:

```powershell
# Build and run containers
docker compose up --build

# Run in background (detached)
docker compose up -d

# Check service health
docker compose ps

# View backend logs
docker compose logs -f backend
```

---

## 3. Production Hardening & Security Setup

When running with `ENVIRONMENT=production`, the application operates in **Secure by Default** mode:

### Required Secrets Checklist
Production startup **strictly refuses to initialize** (`RuntimeError`) unless the following environment variables are present in `backend/.env`:

| Variable | Description | Generation Command |
| :--- | :--- | :--- |
| `APP_ADMIN_PASSWORD_HASH` | SHA-256 hash with salt for site owner login | `python -c "from app.core.security import hash_password; print(hash_password('YourMasterPassword'))"` |
| `SESSION_SECRET` | 32+ character HMAC key for signing session tokens | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `TOKEN_ENCRYPTION_KEY` | 32-byte url-safe base64 key for Fernet OAuth cipher | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed origins (no wildcard `*`) | `http://localhost:3000,http://127.0.0.1:3000` |

### Reverse Proxy & Client IP Verification
If deployed behind a reverse proxy (e.g. Nginx, Traefik, or Caddy):
- Configure `TRUSTED_PROXIES` with the reverse proxy's internal IP address (e.g. `TRUSTED_PROXIES=127.0.0.1,10.0.0.1`).
- The backend will ignore `X-Forwarded-For` unless the connecting peer socket matches a trusted proxy, preventing client IP spoofing in rate limiters.

### Cookie Flags in Production
In production mode, the authentication cookie (`session_id`) enforces:
- `HttpOnly`: Prevents client-side script access.
- `Secure`: Transmitted only over HTTPS.
- `SameSite=Lax`: Prevents cross-site request forgery while preserving top-level navigation.

---

## 4. Operational Monitoring & Health

The backend provides a dedicated, lightweight healthcheck endpoint exempt from authentication:

```bash
curl http://localhost:8000/healthz
# Returns: {"status": "ok", "environment": "production", "version": "1.6.0"}
```

Startup auto-recovery automatically marks any crawler or pipeline jobs that were left in an interrupted state during unexpected shutdowns as `interrupted`, allowing subsequent safe resumption.
