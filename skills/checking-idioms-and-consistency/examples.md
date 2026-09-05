# Examples — checking-idioms-and-consistency

Report each distinct issue as its own numbered finding. When the input is correct, the entire response is exactly "No findings" — never produce a numbered list of findings for correct code. The codebase's established
convention wins over personal preference — read the project's config/style and
sibling code first; consistency findings must point at the existing convention
being diverged from.

## Contents

- [Bad → finding](#bad--finding)
- [Bad → finding](#bad--finding-1)
- [Good → no finding](#good--no-finding)
- [Good → no finding (no established convention to compare against)](#good--no-finding-no-established-convention-to-compare-against)
- [Not applicable → outside this lens's scope](#not-applicable--outside-this-lenss-scope)

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

## Good → no finding (no established convention to compare against)

**Input (diff, with context):**

```ruby
# Project context: this Rails app predates any team style guide; RuboCop was
# never adopted. Existing controllers mix snake_case and camelCase instance
# variables, string and symbol hash keys, and both `unless` and `if !` with
# no discernible pattern across the codebase.
def show
  @user_record = User.find(params[:id])
  render json: { "name" => @user_record.name }
end
```

**Expected finding:** None — there is no established formatter, linter, or
documented convention in this codebase to compare the diff against, so this
lens has no baseline to check consistency with. Report "No findings". Do NOT
pick one of several already-competing styles as "the" house convention and
flag the diff for not matching it — the team hasn't settled that question,
and this lens shouldn't settle it for them diff-by-diff.

## Not applicable → outside this lens's scope

**Input (diff, with context):**

```json
// tests/fixtures/mock_api_response.json
{
  "status": "ok",
- "retry_after_seconds": 42
+ "retry_after_seconds": 43
}
```

**Expected finding:** This change has no code shape, formatting, or naming
surface at all — it's a single numeric value edited in a test fixture, not
source code. Report "Not applicable: this change has no code shape,
formatting, or convention surface for this lens to check". Do NOT report "No
findings" here — that sentence means the code was checked against project
convention and matched it, which implies there was code to check. There
wasn't any.
