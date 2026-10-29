# Security policy

RL Clipper runs locally and listens only on `127.0.0.1`. Still, if you find a security problem, please report it privately rather than in a public issue. Examples:

- a way to read or write files outside the app's folders through its API;
- a way for a web page to control the local server;
- something unsafe in how replay files or videos are parsed.

## How to report

Use GitHub's **[private vulnerability reporting](../../security/advisories/new)** (Security tab → "Report a vulnerability"). Please include:

- steps to reproduce;
- the affected version or commit;
- the impact.

You'll get a reply as soon as possible, normally within a week. Please don't share the details publicly until a fix is released.

## Supported versions

Only the latest release on `main` gets security fixes.
