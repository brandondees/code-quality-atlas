# References to mine — reviewing-concurrency-and-async

## Contents
- From category #3

## From category #3

### Key references
- **Brian Goetz et al. — *Java Concurrency in Practice*** → mine: happens-before, atomicity vs. visibility, safe publication — the vocabulary for reasoning about shared mutable state.
- **Martin Kleppmann — *Designing Data-Intensive Applications*** → mine: replication/consistency models, the perils of distributed time, and "exactly-once" reframed as idempotency.
- **Leslie Lamport — "Time, Clocks, and the Ordering of Events in a Distributed System" (CACM, 1978)** → mine: the *happens-before* partial order; you cannot rely on wall-clock ordering across nodes.
- **Idempotent Consumer pattern (multiple sources, 2024–2026)** — e.g. https://www.milanjovanovic.tech/blog/the-idempotent-consumer-pattern-in-dotnet-and-why-you-need-it → mine: at-least-once delivery + idempotent processing ≈ effective exactly-once; dedupe on a stable business key, stored with the operation, with a TTL.
- **Julik Tarkhanov — frontend race reviews (prior art)** `(verify URL)` → mine: DOM-lifecycle / event-timing races in JS/Stimulus controllers (node gone after `await`).
