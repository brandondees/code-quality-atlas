# Tool rules to triage — reviewing-concurrency-and-async

> **Selecting tools for this stack.** The tools named below are field-tested starting points, not a mandate. Pick the one that fits this codebase's language version, build, and CI — and verify it actually runs on your toolchain before relying on it. A listed tool that is broken, abandoned, or noisy on your setup is a gap to close, not a permanent `continue-on-error`: prefer a working, maintained equivalent (often a younger, less well-known one) over a canonical-but-broken default. The capability is the requirement; the specific tool is replaceable.

## Contents

- From category #3

## From category #3

### Tooling rules worth lifting

- **ESLint / typescript-eslint:** `require-atomic-updates` (read-modify-write across `await`/`yield` → race), `no-await-in-loop` (often accidental sequential where `Promise.all` was meant — correctness + perf), `no-floating-promises`, `no-misused-promises`.
- **Go:** `go test -race` — dynamic data-race detector; **no false positives, but only catches races your tests actually exercise; misses deadlocks, livelocks, and logical races** (https://go.dev/doc/articles/race_detector). `go vet` analyzers: `copylocks` (lock copied by value), `atomic` (misuse of `sync/atomic`), `lostcancel` (context cancel func not called → leak; cross #4).
- **JVM:** SpotBugs multithreaded-correctness detectors (e.g. `IS2_INCONSISTENT_SYNC`); Error Prone `@GuardedBy`.
- **Ruby:** `rubocop-thread_safety` — `ThreadSafety/ClassAndModuleAttributes`, `ThreadSafety/MutableClassInstanceVariable`.
- **C/C++/Go:** ThreadSanitizer (TSan) for data races; **Helgrind** (Valgrind) for lock-order/deadlock.
