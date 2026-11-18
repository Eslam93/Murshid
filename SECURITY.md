# Security policy

## Reporting a vulnerability

Please do not report security problems in public issues, pull requests or discussions. Report
them privately through GitHub security advisories: on the repository's **Security** tab, choose
**Report a vulnerability**, or go straight to
<https://github.com/Eslam93/Murshid/security/advisories/new>.

A useful report says what you found, how to reproduce it (the question, the provider and the
settings), and what an attacker or a misled user could do with it. Leave real API keys and real
personal data out of the report. The maintainer will acknowledge the report, keep you updated
while it is fixed, and credit you in the published advisory if you would like that.

## Scope

Murshid answers questions about government services, so a wrong answer can cost someone money or
a deadline. These are in scope:

- **Prompt injection.** Text in a question or in a source passage that makes the system ignore
  its instructions, reveal its prompts, or get past the router, the support gate or the critic.
- **Data leakage.** Answers, logs or bench artifacts that expose API keys, system prompts, other
  users' questions or anything else that should stay private.
- **Personal-data handling.** Personal data that users type, such as national ID, iqama, passport
  or IBAN numbers, being stored, logged or sent to a model provider without masking.
- **Answers that invent government policy.** An answer that states a fee, rule, deadline,
  exemption or procedure that its cited sources do not support, especially where the support gate
  or the critic should have refused.

Out of scope:

- The contents of the demo corpus. It is synthetic on purpose and is not official guidance (see
  [data/README.md](data/README.md)).
- Vulnerabilities in third-party packages or model providers that Murshid's use does not make
  worse. Please report those upstream.

## Supported versions

Fixes go to the `main` branch. There are no separately maintained release branches.
