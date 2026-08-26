# LAN HTTPS readiness

`PUBLIC_BASE_URL` lets the startup QR and displayed Mobile URL use a stable published API address while leaving the API listener unchanged. This is a readiness slice only: it does not enable HTTPS today.

## Quick path

1. Keep the current HTTP LAN fallback until hostname resolution, proxy, and device trust are verified.
2. After those prerequisites work, set `PUBLIC_BASE_URL=https://api.estacionamiento.lan/api/v1` in `.env`.
3. Start `run.ps1` and scan the QR or enter the displayed full URL on the Sunmi.

## Contract

| Setting | Rule |
| --- | --- |
| `PUBLIC_BASE_URL` | Optional absolute `http` or `https` URL. HTTPS is the operational target; HTTP remains accepted for staged migration. |
| Path | Must be exactly `/api/v1`, without a trailing slash. |
| Other URL parts | Query strings, fragments, and user information are rejected. |
| When present | `run.ps1` normalizes and uses the URL for both the QR and manual Mobile guidance. |
| When absent | `run.ps1` detects a LAN IPv4 address and uses `http://<LAN-IP>:<API_PORT>/api/v1`. |

The official hostname-resolution contract is managed DNS or managed router DNS for every operational device. Manual hostname configuration on individual devices is an emergency fallback only; it is not a supported deployment model.

## Future HTTPS topology

The recommended next slice is Caddy as a reverse proxy on the server. It should accept HTTPS for the managed LAN hostname and proxy to the API on loopback. An internal CA issues the certificate, and its root CA must be trusted by each Sunmi before clients use the HTTPS URL.

Example only; do not apply this file as configuration:

```caddyfile
https://api.estacionamiento.lan {
    tls /path/to/certificate.pem /path/to/private-key.pem
    reverse_proxy 127.0.0.1:8000
}
```

Certificate paths and private material are placeholders. Do not store private keys, CA roots, or other secret material in this repository.

## Out of scope

This slice does not enable HTTPS, install or configure Caddy, generate certificates or a CA, change firewall rules, change services or health checks, alter API bind/port/protocol, or make Mobile HTTPS-only.

## Rollback

Clear `PUBLIC_BASE_URL` and restart with the current HTTP LAN fallback. Do this if DNS, the reverse proxy, certificate issuance, or Sunmi trust is not fully validated.
