# Owner-email pepper — key ceremony & transport

This document describes how the **blind-index pepper** for the lineage-assets
`owner_email_hash` field is stored, transported, and rotated. The index maths
itself is HMAC-SHA256 (see `SCHEMA.md` and `scripts/lib/blind_index.py`); a
public-key index would be simultaneously guessable and non-deterministic, so the
key pair below is used **only to wrap/transport the pepper**, never as the index.

## Where each secret lives

| Secret | Location | Published? |
|---|---|---|
| `owner_email_pepper` | autopilot vault (`/opt/truesight_autopilot/vault`) **and** repo secret `OWNER_EMAIL_PEPPER` on `TrueSightDAO/lineage-assets` | No |
| `owner_email_pepper_wrap_private` (RSA-2048 private key) | autopilot vault **only** | No |
| `owner_email_pepper_wrap_public` (RSA-2048 public key) | vault **and** `keys/owner_email_pepper_wrap.pub.pem` in this repo | **Yes** (public by design) |

`GOOGLE_CREDENTIALS_JSON` (the Agroverse ledger-manager service account) is also a
repo secret on `lineage-assets`; it is unrelated to the pepper and is a standard
read-only Sheets credential.

The box cron (`sync_pending_caches.py`) does **not** compute tokens — it only
copies `owner_email_hash` out of the published index. Therefore the pepper is
**required only in CI** and is deliberately **not** installed on the autopilot
box `.env` (keeps secret sprawl down).

## Wrapping the pepper for transport

Only needed when handing the pepper to a new environment. Requires the public
key (this repo) and the plaintext pepper (vault):

```bash
# 1. write the plaintext pepper to a temp file (from the vault)
python3 - <<'PY'
import sys; sys.path.insert(0, '/opt/truesight_autopilot')
from app.vault import get_vault
open('/tmp/pepper.txt', 'w').write(get_vault().get_value('owner_email_pepper'))
PY

# 2. wrap it with the public key (RSA-OAEP / PKCS#1 v1.5)
openssl pkeyutl -encrypt -pubin \
  -inkey keys/owner_email_pepper_wrap.pub.pem \
  -in /tmp/pepper.txt -out /tmp/pepper.enc

# 3. scrub the plaintext
shred -u /tmp/pepper.txt
```

The resulting `pepper.enc` is safe to move over any channel. To unwrap, the
holder needs the **private** key (vault-only):

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '/opt/truesight_autopilot')
from app.vault import get_vault
open('/tmp/priv.pem', 'w').write(get_vault().get_value('owner_email_pepper_wrap_private'))
PY
openssl pkeyutl -decrypt -inkey /tmp/priv.pem -in /tmp/pepper.enc -out /tmp/pepper.txt
shred -u /tmp/priv.pem
```

## Fail-closed behaviour

If `OWNER_EMAIL_PEPPER` is unset in CI, `compute_owner_email_hash()` returns
`None` and `owner_email_hash` is published **blank** — an unpeppered SHA-256 of an
email is guessable and is **never** used as a fallback. The workflow raises a
`::warning::` in that case.

## Rotation

Rotating the pepper **invalidates every previously published token** (all owner
lookups break until the cache is rebuilt). Treat rotation as a key ceremony:

1. Generate a new value and `vault.update('owner_email_pepper', new)`.
2. `gh secret set OWNER_EMAIL_PEPPER --repo TrueSightDAO/lineage-assets`.
3. Trigger `sync-lineage-assets.yml` (`workflow_dispatch`) to republish tokens.
