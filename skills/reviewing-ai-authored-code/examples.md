# Examples — reviewing-ai-authored-code

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never manufacture an AI-defect finding for correct code just because it might have been machine-written.

## Bad → finding

**Input (diff):**

```diff
# requirements.txt
+ requests-oauth2client-helper==0.3.1   # handy OAuth2 refresh wrapper
```

```python
from requests_oauth2client_helper import OAuth2Session
session = OAuth2Session(client_id=CID, client_secret=CSECRET, auto_refresh=True)
```

**Expected finding:**

1. **Package existence / slopsquat risk (xref #18):** `requests-oauth2client-helper`
   is a plausible-but-unverified name sitting one step from real packages
   (`requests-oauth2client`). ~20% of LLM-suggested packages don't exist and the
   hallucinations recur, so attackers pre-register them. Confirm it actually exists
   on the index, predates this PR, and is the intended project *before* trusting it;
   pin/lock it and hand the reputation/CVE verdict to
   `auditing-dependencies-and-supply-chain`. Do not assume it is real because the
   import reads plausibly.

## Bad → finding

**Input (diff):**

```diff
+ # responses are valid for one day
+ CACHE_TTL_SECONDS = 84600
+ redis.setex(key, CACHE_TTL_SECONDS, payload)
```

**Expected finding:**

1. **Confident-but-wrong constant:** the comment says "one day" but 84600 ≠ 86400
   (one day in seconds) — a transposed-digit slip that reads correctly and fails
   quietly. Verify magic constants against the spec rather than trusting the fluent
   comment; plausibility is the characteristic AI-code failure mode.

## Bad → finding (over-helpful scope creep)

**Input (diff):** a PR asked only to reword one validation message also adds a new
`/admin/users/export` endpoint, a `RETRY_ENABLED` flag, and a broad-`except
Exception` retry helper.

**Expected finding:**

1. **Over-helpful, unrequested additions:** the typo-fix PR ships a new admin export
   endpoint, a global flag, and a retry wrapper — scope creep that widens the diff
   and blast radius beyond the stated task. Route the keep-or-defer call to
   `checking-restraint`; the smuggled-in export endpoint needs its own
   security/contract review (and the broad `except Exception: continue` swallows
   errors) rather than riding in on a typo fix. Scope the PR back to the message
   change.

## Good → no finding

**Input (diff):**

```python
import httpx  # already a pinned dependency in requirements.txt

def get_user(client: httpx.Client, user_id: int) -> dict:
    resp = client.get(f"/users/{user_id}", timeout=5.0)
    resp.raise_for_status()
    return resp.json()
```

**Expected finding:** No findings

Note: a real, already-present pinned dependency used with a correct, current API
(timeout set, `raise_for_status` before parsing), no hallucinated symbols, no scope
creep, no confident-but-wrong constants. Do NOT invent AI-defect findings on correct
code, and do NOT flag the f-string path or the URL parameter as inherently unsafe.
