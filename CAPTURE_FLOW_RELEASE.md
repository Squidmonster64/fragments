# Fragments one-login capture flow

Human path:

1. Authenticate to Fragments once.
2. Tap record, speak, tap stop — or type and save.
3. Preserve the Fragment locally/server-side first.
4. Voice is transcribed automatically.
5. The saved words are interpreted and handed to the existing Hope Task Capture Engine automatically.
6. Only after routing succeeds does the outbox report `Captured and routed`.
7. If routing is unavailable, the Fragment remains preserved and the outbox reports `Saved · routing needs retry`.

The old per-Fragment Hope Task live-sync passphrase is not part of this human path and is hidden from the product UI. No credential values are copied between services. No Capture Engine classification rules are changed.