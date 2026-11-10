# LocalMind security notes

## Local trust boundary

Phase 2 assumes the admin service runs on a trusted local network only. Do not expose the admin service publicly, and do not rely on plain HTTP on untrusted Wi-Fi networks. The Phase 11 TLS and certificate-pinning work remains out of scope.

## Secret handling

- Admin passwords are stored only as salted scrypt hashes.
- Pairing codes are stored as SHA-256 hashes.
- Worker bearer tokens are stored only as SHA-256 hashes.
- Tokens are never logged, shown in the dashboard, or printed by the worker CLI.
- Worker configuration is saved under the platform-appropriate configuration directory and restricted to 0600 permissions where supported.

## Revocation and credential lifecycle

- Pairing codes expire after 10 minutes.
- A pairing code can be redeemed once only.
- Revoked workers are rejected with HTTP 403.
- Unpairing removes the local config first and then attempts a remote revocation when the admin is reachable. If the admin is unreachable, the local credentials are still removed and the user is warned that remote revocation requires attention.

## Credential storage

The worker stores only:

- admin URL
- worker ID
- bearer token

The file is saved in `~/.config/localmind/worker.json` on Linux/macOS and `%APPDATA%/LocalMind/worker.json` on Windows.
