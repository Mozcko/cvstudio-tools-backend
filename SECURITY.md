# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report them privately through GitHub: go to the repository's **Security** tab and choose
**Report a vulnerability**
([direct link](https://github.com/Mozcko/cvstudio-tools-backend/security/advisories/new)).

Include, as far as you can:

- what an attacker could do, and what they would need to do it;
- the endpoint, request and response that show the problem;
- the commit or deployment you tested against.

Please do not access, change or delete data that is not yours while testing, and give us a
reasonable time to fix the problem before disclosing it.

You can expect an acknowledgement within a few days. We will keep you informed while we work on a
fix and credit you in the advisory unless you prefer otherwise.

## Supported versions

Only the latest commit on `main` — the version that is deployed — receives security fixes.

## How the project guards against regressions

- Authentication, webhook verification, PII masking and rate limiting are covered by tests that
  run on every pull request.
- CI audits the dependencies for known vulnerabilities on every pull request and once a week.
- CodeQL scans the code on every pull request and once a week.
- Dependabot proposes dependency updates weekly.
