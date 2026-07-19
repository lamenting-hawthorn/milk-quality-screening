# Hosted deployment boundary

The included Supabase adapter is a server-side integration example. It is not a
multi-tenant application deployment. Do not expose `SUPABASE_SERVICE_ROLE_KEY`
in a browser, mobile app, spreadsheet macro, or public client.

## Minimum production architecture

Before hosting this project for more than one collection organization, provide:

1. An `organizations` table and an immutable organization ID on every derived
   record, review case, and report bundle.
2. Authenticated users and membership records that bind each request to exactly
   one organization.
3. Row-level security on every tenant table, tested with two organizations.
4. A server API that derives the organization from identity—not from a request
   field—and uses a narrowly scoped service credential only where unavoidable.
5. Per-period idempotency keys, transactional writes, durable artifact storage,
   retry classification, backups, and an audit log of user actions.

## Required security tests

- A user in organization A cannot read, insert, update, or infer data from B.
- A request cannot select historical statistics outside its organization.
- A failed upload can be retried without duplicate signals, cases, or reports.
- A privileged key is absent from all client bundles, logs, issues, and examples.
- Review-case dispositions are attributable to an authenticated operator.

Until these controls exist, run the local SQLite workflow per trusted operator
or keep the hosted adapter behind a controlled internal service.
