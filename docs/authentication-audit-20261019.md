# Authentication incident and implementation review — 19 October 2026

## Architecture examined before implementation

The web app is a Next.js 16.2.1 BFF. Django issues signed access tokens (15 minutes by default) and rotating refresh tokens backed by PostgreSQL AuthTokenSession rows. Refresh families have an absolute lifetime (30 days by default). Web credentials stay in Secure, HttpOnly, SameSite cookies; BFF JSON removes bearer credentials. Server Components can read cookies but cannot persist rotations. Proxy renews page requests; Route Handlers renew API requests. Django checks the session, user, profile scope, signature, issuer, audience and expiry. PostgreSQL row locks and a bounded previous-generation grace window support overlapping requests and workers. Logout revokes the family. Flutter consumes the same JSON API, serializes foreground refreshes and preserves sessions on transient failures; its wire contract must remain compatible.

## Confirmed findings

- Production Redis was in a restart loop: its multipart AOF had an invalid trailing 2,559 bytes (valid offset 25,548,289 of 25,550,848). An untouched backup was saved under `/opt/edilcloud/releases/redis-before-auth-repair-20261019/data`. The Redis checker validated the RDB and repaired only the invalid tail. Redis returned PONG and public health reported cache=ok afterwards. PostgreSQL auth-session rows were not changed by this repair.
- Refresh rate limiting uses Redis. A Redis connection failure escaped as a generic server error. Rate limiting must remain enforced: infrastructure failure should return retryable 503, without minting credentials or revoking the family.
- `getServerAuthSession` throws an ordinary Error for expected verification/refresh unavailability. At `/` and `/auth` there is no local error boundary: this reaches the production Server Components error screen.
- Proxy verifies every fresh token, then the page verifies it again. Prefetch/navigation and BFF fan-out increase round trips. Page verification in the DAL remains authoritative; Proxy only needs expiry-based renewal.
- Proxy's matcher omits `/evidenze`, despite that page requiring auth. Refresh-only evidence links therefore cannot recover during SSR.
- Page recovery currently has no route that can safely persist new cookies, retry temporary failures and restore the original destination.
- The existing `/health` returns HTTP 200 even when its cache check fails. A readiness check should explicitly detect unavailable dependencies, separately from liveness.

## Implementation and verification contract

1. Preserve the Django/Flutter token formats, session revocation, absolute expiry, replay detection, profile isolation and no-credentials-in-browser-JSON rules.
2. Renew in Proxy/Route Handlers only. Verify authorization in the DAL and backend. Do not trust decoded JWT claims as authorization or cache an accepted session across requests.
3. For pages, redirect expected auth unavailability to a dedicated recovery screen. Retry the no-store session endpoint with bounded backoff and return only to a validated same-origin page path. Keep credentials on timeout/429/5xx. Clear credentials only for a definitive session rejection.
4. Ensure all page routes participate, strip/overwrite any client-supplied internal routing metadata, and do not repeat verification for fresh tokens in Proxy.
5. Return 503 + Retry-After for unavailable rate-limit storage without bypassing it. Bound Redis connection/read waits. Add dependency readiness and regression tests.
6. Test backend invariants, actual Next production rendering and browser recovery, concurrent renewals, expired access, rejected refresh, cookie persistence, logout and cross-origin mutations. Push only this work, deploy, then verify the public backend and frontend.

## Primary guidance reviewed

- [Next authentication and DAL](https://nextjs.org/docs/app/guides/authentication): centralize secure checks near the data source; avoid repeated database checks in Proxy/prefetch.
- [Next cookies](https://nextjs.org/docs/app/api-reference/functions/cookies): Server Components cannot write cookies.
- [Next expected errors](https://nextjs.org/docs/app/getting-started/error-handling): handle failed requests explicitly instead of throwing generic render exceptions.
- [RFC 9700 §4.14](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14): rotation, expiration and replay detection for refresh credentials.
- [Redis persistence recovery](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/): back up the AOF before checking/repairing it.

Validation results and release identifiers will be recorded after the checks run. No finite verification can guarantee absence of all future infrastructure/authentication failures.

## Why the Redis file was corrupt

The preserved original's invalid tail contains exactly 2,559 NUL bytes, rather than an incomplete Redis command. Its mtime is 18 October 15:05:36 Europe/Rome. The previous system journal stops at 15:05:31 and the next boot starts at 15:30:37. Docker also reports NUL bytes in its own log after that boot. This is strong evidence consistent with an abrupt VM/storage interruption during writes, affecting multiple files. It does not prove whether the initiating fault was a provider reset, power loss, or storage failure; that attribution requires provider-side records. The inspected kernel logs contain no OOM-kill or disk-I/O-error evidence. Current free RAM, free disk and inodes do not prove their values at the incident time.

Redis's `appendfsync=everysec` and `aof-load-truncated=yes` were checked: the latter can recover a truncated command but not an all-zero corrupt record. Do not automatically delete the AOF or silently truncate future corruption. Preserve the original, check the backup and use `redis-check-aof --fix` only after reviewing the affected tail. The recommended `vm.overcommit_memory=1` host setting was applied persistently in `/etc/sysctl.d/60-edilcloud-redis.conf`; it avoids a separate documented Redis background-save/fork problem and is not presented as the cause of this corruption.

Monitoring previously checked only whether the Redis exporter HTTP endpoint responded. The new `EdilCloudRedisUnavailable` rule checks `redis_up=0`, detecting an unavailable Redis server even while its exporter stays up. Readiness now also checks the dependencies required for authentication before switching production traffic to a release.
