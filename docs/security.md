# Security

## Threat Model (MVP)
Alter can execute local actions via tools. When exposed over the network (even via a private VPN like Tailscale),
unauthorized access would be catastrophic. Therefore we default to:
- API key required for HTTP + WebSocket
- Confirmation required for tool execution
- Shell tool restricted by allowlist

## API Key Handling (Browser-Friendly)
Browsers cannot set custom headers on WebSocket connections. For the MVP:
- HTTP endpoints accept either:
  - header `X-Alter-Key: ...`, or
  - query parameter `?key=...`
- WebSocket auth uses `?key=...`

Note: putting keys in URLs can leak via browser history and screenshots. Use `/?key=...` once, then reload without the query string.

## Defaults
- `security.require_api_key: true`
- `security.require_confirmation: true`
- `security.allowed_commands`: minimal allowlist
- `security.max_requests_per_minute`: basic in-memory rate limit for `/v1/*`

## Simple Per-User Tokens (MVP)
For now, Alter uses a shared API key. If you want one token per user/device:
- Set `security.api_keys` to a list of allowed tokens.
- Share one token per person/device.
- Revoke access by removing that token from the list.

If `security.api_keys` is non-empty, `security.api_key` is ignored.

## Remote Access (Tailscale)
Recommended approach:
1. Install Tailscale on PC and phone.
2. Ensure both are in the same tailnet.
3. Use the Tailscale IP address of your PC to reach the web UI.
4. Set a strong `security.api_key` and keep it private.

## Logging & Audit
Alter writes:
- Application logs: `data/logs/alter.log` (planned)
- Tool audit events: `data/audit.jsonl`

Audit entries include:
- tool id, inputs, timestamps, status, stdout/stderr, exit codes (when applicable)

## Future Hardening
- Per-tool capability tokens
- Rate limiting
- Separate low-privilege tool runner process
- Per-device session tokens instead of a shared API key

## Notes on Web Automation
Rendered browsing (`web.visit_rendered`) uses browser automation (Playwright). When exposed over the network:
- Treat it as powerful remote code execution surface (it can load arbitrary pages).
- Keep API keys private and prefer a private VPN (e.g., Tailscale).
