# Cloud documents: isolated feasibility spike

This is a metadata-only, in-memory experiment. It is **not installed, imported,
routed or enabled by the Django application**. No database migrations, OAuth
credentials, HTTP requests, remote file mutations, uploads or downloads occur.
`ReferenceIndex` is disabled by default; tests explicitly enable their private instance.

It proves strict permission policies, canonical file references, overlapping
folder bindings, atomic checkpoint changes, disconnect behavior and protection
of the drawing revision. It does not prove real Google/Microsoft authorization,
durable synchronization or drawing rendering.

Run from the backend repository:

```powershell
..\venv\Scripts\python.exe -m pytest experiments/cloud_documents/test_spike.py -q
```

Remove `experiments/cloud_documents/` to remove the experiment. No deployed
document rows, files, existing endpoints or authentication flows depend on it.
The production integration must be designed and enabled separately, after the
account/permission spike described in the workspace assessment has passed.

Trust boundaries:

- `provider_grants_verified` and ancestors must be obtained by a server adapter;
  they are not claims accepted from the client.
- `actor_projects`, `can_manage`, and `owns_connection` are synthetic inputs in
  this spike. Production must derive them from active project membership and
  connection ownership, never request payloads.
- An in-memory checkpoint check is not a distributed lock. A real worker needs
  durable transactions, fencing/CAS and a lock per connection/binding.
- Google folder sharing must use a dedicated principal, no domain-wide
  delegation, and a real out-of-scope denial test. An ordinary user OAuth token
  with a wide scope and a folder filter does not satisfy the requirement.
- Microsoft Selected permissions require both consent and explicit resource
  assignment. Delta/webhook support must be verified under those exact grants;
  a restricted paginated folder inventory is the fallback.
- Drawing revision retention is metadata only. Keeping an old drawing usable
  requires provider revision retrieval or an explicitly approved rendition cache;
  the spike does not preserve historical bytes.
