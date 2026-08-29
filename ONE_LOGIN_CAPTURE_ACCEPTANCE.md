# Acceptance

- Fragments owner login remains the only user-facing passphrase gate.
- Voice capture requires only Start and Stop.
- Typed capture uses the same durable outbox as voice.
- Capture is preserved before network routing.
- Voice transcription is automatic.
- Routing through `/api/fragments/:id/interpret` is automatic.
- That endpoint uses the existing server-to-server Hope Task Capture Engine handoff.
- Outbox says `Captured and routed` only after the Capture Engine accepted the capture.
- Capture Engine unavailable => preserved capture + retry state, never silent success.
- Legacy `#live-sync` second-passphrase panel is not visible.
- Capture Engine classification semantics are unchanged.
