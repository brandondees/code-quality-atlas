# References to mine — auditing-architecture-conformance

## Contents
- From category #12

## From category #12

### Key references
- **Robert C. Martin — *Clean Architecture* / The Dependency Rule + Acyclic Dependencies Principle** → mine: source dependencies point inward toward policy; **no cycles** between components. (Treat the dogma critically; mine the dependency-direction and ADP checks.)
- **Mark Richards & Neal Ford — *Fundamentals of Software Architecture*** → mine: architecture *characteristics* (the "-ilities") as first-class, architecture quanta, and the menu of styles with their explicit trade-offs.
- **Neal Ford, Rebecca Parsons, Patrick Kua — *Building Evolutionary Architectures*** → mine: **fitness functions** — automated, objective checks that the architecture still holds ("domain imports no infra", "no package cycles"). Directly inspires architecture-as-test behavior.
- **Foote & Yoder — "Big Ball of Mud"** → mine: the canonical anti-pattern to detect — no discernible structure, everything coupled.
- **Eric Evans — *DDD* (bounded contexts, context mapping)** → mine: module/service boundaries follow **domain** boundaries; cross-context integration via explicit contracts, never shared internals.
