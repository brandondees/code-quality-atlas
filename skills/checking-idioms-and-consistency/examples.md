# Examples — checking-idioms-and-consistency

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code. The codebase's established
convention wins over personal preference — read the project's config/style and
sibling code first; consistency findings must point at the existing convention
being diverged from.

## Bad → finding

**Input (diff, with context):**

```python
# Project convention everywhere else: raise ApiError(code, message);
# middleware builds the response. Style: ruff + "is None" enforced.
def get_user(req):
    user = find(req["id"])
    if user == None:
        return {"error": "not found", "status": 404}
    names = []
    for key in user.keys():
        names.append(key)
    return names
```

**Expected finding:**

1. **Second way to do the same thing:** the ad-hoc `{"error": ..., "status": ...}`
   dict diverges from the project's `raise ApiError(code, message)` convention —
   callers and middleware now have two error shapes to handle.
2. **Non-idiomatic comparison:** `== None` → `is None` (and the project's linter
   enforces it).
3. **Clumsy non-native construct:** the manual loop over `user.keys()` is
   `list(user)` — use the idiomatic form.

## Bad → finding

**Input (diff, with context):**

```js
// Project has src/utils/formatDate.ts used in 40+ call sites; camelCase enforced.
export function date_to_string(d) {
  const yyyy = d.getFullYear();
  return `${yyyy}-${d.getMonth() + 1}-${d.getDate()}`;
}
```

**Expected finding:**

1. **Parallel utility:** `date_to_string` duplicates the existing `formatDate`
   helper — a second competing way to format dates. Use or extend the existing one;
   if it can't serve this case, state why in the PR.
2. **Naming-convention break:** `date_to_string` is snake_case in a camelCase
   codebase.

## Good → no finding

**Input (diff, with context):**

```python
# Project convention: raise ApiError; pathlib over os.path; ruff clean.
def read_manifest(path: Path) -> dict:
    if not path.exists():
        raise ApiError("manifest_missing", f"no manifest at {path}")
    return json.loads(path.read_text())
```

**Expected finding:** None — follows the project's error convention, idiomatic
pathlib, formatter-clean. Report "No findings". Do NOT impose personal style
preferences over the project's established choices, and apply the counterweight:
if two call sites genuinely differ, divergence is correct — do not demand
consistency that erases a meaningful difference.
