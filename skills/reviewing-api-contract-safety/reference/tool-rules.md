# Tool rules to triage — reviewing-api-contract-safety

## Contents
- From category #13

## From category #13

### Tooling rules worth lifting
- **Spectral** (Stoplight) — lint OpenAPI/AsyncAPI against a style guide (naming, required fields, consistency). (https://stoplight.io/open-source/spectral)
- **oasdiff** — OpenAPI **breaking-change detection** (470+ change types) + diff; CLI + GitHub Action. (https://www.oasdiff.com/)
- **buf** — Protobuf breaking-change detection (`WIRE`, `WIRE_JSON`, `PACKAGE`, `FILE` categories) + lint. (https://buf.build/docs/breaking/)
- **Pact / Pactflow** — consumer-driven contract tests across the consumer-provider boundary.
- **GraphQL** — graphql-inspector (schema breaking changes), graphql-schema-linter.
- **Google api-linter** (AIP rules) for gRPC/REST conventions.
