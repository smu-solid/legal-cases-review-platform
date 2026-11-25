# Architecture

The backend is a modular monolith. HTTP routes translate requests into service operations;
services enforce authorization and tenant scope and own workflow transitions. Request-scoped
transactions commit complete operations. Database constraints, row-level security and locking
provide additional isolation and concurrency protection.

## Input and application state

The dataset reader opens SQLite in read-only mode and validates case/document identities.
Import writes application-owned snapshots, review subjects, units, candidates, evidence and
artifact metadata into PostgreSQL. Campaign creation draws eligible units from the shared pool.
Reviewers never modify the input dataset.

PostgreSQL also owns users, memberships, grants, revocable sessions, campaign rosters, allocation
plans, assignments, drafts, submissions, proposals, adjudication participation and decisions.
Audit records form an append-only authenticated chain.

## Documents and provenance

The importer sanitizes HTML and generates a deterministic text projection. Evidence offsets refer
to that text rather than HTML bytes. Artifact bodies and anchor maps live in a private filesystem
store; PostgreSQL stores their keys and hashes. Authorized API routes verify hashes before serving
artifacts. The browser supports text and document views and records corrections separately.

Evidence from a different document is never highlighted as if it belonged to the displayed one.
An unavailable location remains explicitly unavailable.

## Identity and authorization

Email/password sign-in issues an opaque HttpOnly session cookie. Only token digests are stored.
Session expiry, account suspension, authorization epochs and revocation are checked on requests.
Browser mutations require an allowed Origin and matching session-bound CSRF token.
Role/capability visibility in the UI is advisory; the backend enforces authorization.

## Frontend

Pages compose domain controllers and presentation components. Queries and writes use the versioned
HTTP API. Reviewer bundles exclude peer submissions and allocation internals. Authorized
adjudication workspaces expose submissions and independent participant decisions.
