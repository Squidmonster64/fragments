# Offline contract — Fragments

| Capability | Offline |
| --- | --- |
| Launch if cached | Yes |
| Read cached/local | Recent local captures if the outbox/cache still holds them |
| Create | Voice and typed capture write to the durable outbox |
| Edit / delete | Local draft edits only |
| Voice capture | Yes |
| Typed capture | Yes |
| Queue writes | Yes — durable outbox |
| Sync on reconnect | Yes |
| Conflicts | Server fragment identity wins; local outbox retries |
| Requires internet | Harvest confirm write, remote interpretation beyond cache, suite actions |
