# Research — Sample

## #2 Error handling & resilience

### Key references
- **Nygard — Release It!** → mine: timeouts, circuit breaker, bulkhead.

### Tooling rules worth lifting
- **typescript-eslint:** `no-floating-promises` (unhandled async error).
- **RuboCop:** `Lint/SuppressedException` (empty rescue).

### Reviewable heuristics (skill-checklist seeds)
- Is any error swallowed (empty catch/rescue, `except: pass`)?
- Does every remote call have a timeout?
- Are retries capped with backoff?

## #4 Resource & state management

### Key references
- **Nygard — Steady State** → mine: bound anything that grows.

### Tooling rules worth lifting
- **Go:** `bodyclose` (unclosed HTTP body).

### Reviewable heuristics (skill-checklist seeds)
- Is every acquired resource released on all paths?
- Are caches bounded with eviction/TTL?
