# Tool rules to triage — reviewing-concurrency-and-async

## Contents
- From category #3

## From category #3

### Tooling rules worth lifting
- **ESLint / typescript-eslint:** `require-atomic-updates` (read-modify-write across `await`/`yield` → race), `no-await-in-loop` (often accidental sequential where `Promise.all` was meant — correctness + perf), `no-floating-promises`, `no-misused-promises`.
- **Go:** `go test -race` — dynamic data-race detector; **no false positives, but only catches races your tests actually exercise; misses deadlocks, livelocks, and logical races** (https://go.dev/doc/articles/race_detector). `go vet` analyzers: `copylocks` (lock copied by value), `atomic` (misuse of `sync/atomic`), `lostcancel` (context cancel func not called → leak; cross #4).
- **JVM:** SpotBugs multithreaded-correctness detectors (e.g. `IS2_INCONSISTENT_SYNC`); Error Prone `@GuardedBy`.
- **Ruby:** `rubocop-thread_safety` — `ThreadSafety/ClassAndModuleAttributes`, `ThreadSafety/MutableClassInstanceVariable`.
- **C/C++/Go:** ThreadSanitizer (TSan) for data races; **Helgrind** (Valgrind) for lock-order/deadlock.
