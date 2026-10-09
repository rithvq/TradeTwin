# OAuth Login and Private Profiles

TradeTwin now requires profile sign-in by default. The initial provider is Google;
the issuer discovery URL and displayed provider name are configurable for another
OpenID Connect provider. Register and test that provider's exact issuer settings
before changing them. The current UI supports one configured provider at a time.

## Configure Google

1. In Google Cloud, configure the OAuth consent screen and create an OAuth client
   of type **Web application**. If the application is in testing, add your Google
   account to the test users.
2. Register this authorized redirect URI exactly:
   `http://localhost:3000/api/auth/callback`
3. Set the following values in the root `.env` file. Never commit the real secrets.

```dotenv
PROFILE_AUTH_ENABLED=true
APP_PUBLIC_URL=http://localhost:3000
OAUTH_PROVIDER_NAME=Google
OAUTH_DISCOVERY_URL=https://accounts.google.com/.well-known/openid-configuration
OAUTH_CLIENT_ID=your-client-id
OAUTH_CLIENT_SECRET=your-client-secret
OAUTH_STATE_SECRET=your-random-secret-of-at-least-32-characters
```

Generate a state secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

4. Rebuild all application services because ownership checks live in the backend:

```powershell
docker compose up -d --build
docker compose ps
```

5. Open http://localhost:3000/login and choose **Continue with Google**. Each
   profile starts with its own workspace. **TradeTwin Demo** creates a separate
   demo shipment inside that profile.

Without credentials, the login page displays a configuration message and private
data remains inaccessible. There is no fake login button or shared-token bypass
when profile authentication is enabled. Do not paste provider secrets into chat.

## Data Boundaries

- Profiles are keyed by validated OpenID Connect issuer and subject. Matching
  email addresses alone do not merge accounts.
- The browser receives a random HttpOnly, SameSite=Lax session cookie. Sessions
  expire after 12 hours; only token hashes are stored in PostgreSQL. Logout revokes
  the session immediately. OAuth provider access/refresh tokens are not retained.
- Authlib performs OAuth state, PKCE, nonce and ID-token validation.
- The browser proxy forwards the session server-side and rejects cross-origin
  writes. Backend services validate the session independently, so direct API calls
  cannot bypass authentication by supplying an owner ID.
- Shipments, consignments, routes, events, documents, assessments, questions,
  regulation changes, audit records and risk results are filtered by profile.
  Each profile is the administrator of its own workspace, not other workspaces.
- MinIO object keys include a profile prefix. Files are accessed through owned
  document records. Storage buckets must remain private; there are no public file URLs.
- Infrastructure and API ports bind to localhost by default. Operators with server,
  database or MinIO administrator access still have infrastructure-level access.

## Existing Data

Startup migrations add ownership columns without deleting data. Existing records
remain in `legacy-unassigned`, invisible to OAuth profiles. They are deliberately
not assigned to whichever person logs in first. After signing in, an administrator
can explicitly migrate selected legacy shipments and all related records to the
verified profile ID; back up the database before that separate migration.

Do not remove Docker volumes to enable authentication. `docker compose down -v`
would delete persistent data. PostgreSQL and MinIO volumes retain profiles and files
across ordinary container restarts.

## Verification

```powershell
pip install -e packages/security -r apps/api/requirements.txt
python -m pytest -q
python scripts/profile-security-check.py
```

The integration check uses temporary databases and two generated test sessions.
It checks cross-profile access to shipments, graphs, PDFs, extraction, assessments,
evidence, risk results, and session revocation. These test sessions are inserted
only into isolated test databases; there is no runtime endpoint that issues them.
OAuth unit tests cover callbacks, state/PKCE/nonce generation, expiry and logout.
Live provider sign-in needs your registered client credentials and consent.

For an HTTPS deployment, use the public HTTPS origin in `APP_PUBLIC_URL`, register
its `/api/auth/callback` URL, and terminate TLS at a reverse proxy. Session cookies
automatically use Secure when that origin is HTTPS. Do not expose database/MinIO
admin ports publicly or change private buckets to public access.

References: [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect),
[Authlib Starlette integration](https://docs.authlib.org/en/v1.7.0/oauth2/client/web/starlette.html).
