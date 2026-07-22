# Twisted Protocol Server Capabilities Gameplan

## 1. Mission

Catalog the **server-side** protocol capabilities where Twisted has no real asyncio-ecosystem
equivalent, identify which would genuinely benefit riko, and define the one pattern for adapting
them: an external package that runs Twisted's protocol code on the shared asyncio loop via
`twisted.internet.asyncioreactor`, exposing a riko `Feed` / `Publisher` / `Subscription` (P11) —
**without** Twisted being the engine's runtime (ROADMAP §23.1).

This is a *shelf* plan (like the other connector gameplans): none of it is on the Milestone-1/2
critical path. It exists so the "drop Twisted as the runtime" decision doesn't accidentally throw
away the parts of Twisted that are actually irreplaceable.

## 2. Why server-side, and why Twisted here

riko is a stream-processing engine: a source is something that **emits records over time**. On the
**client** side (poll IMAP, connect IRC, SSH-exec) asyncio-native libraries are as good or better
(`asyncssh`, `bottom`, `aioimaplib`) — use those, no Twisted. Twisted's genuine, unmatched
strength is **listening**: being a server that accepts connections and turns inbound traffic into a
stream. That maps exactly to a riko live push source (a `Publisher`/`Feed` that yields as data
arrives), and it is where asyncio has no batteries-included peer.

## 3. The adaptation pattern (one shape for all of these)

```text
riko-<proto>  (external package; entry-point registered per §24)
    installs twisted.internet.asyncioreactor at import (cooperates with the engine's asyncio loop)
    builds the Twisted server Factory/Protocol
    each inbound message  ->  send() into an AnyIO memory object stream (backpressure)
    exposes:
        a poll/interval or event Subscription (P11)  for pull-style stages, or
        a Feed (AsyncIterable[Item])                 for `async for` consumption
    resources (listening port, factory) live in Context.resources (P11), closed on teardown
```

Rules:
- The reactor is **installed, not run** — Twisted protocol objects fire their callbacks on the
  asyncio loop AnyIO already drives. This is not "a private event loop" (connectors.md §3.1).
- Inbound → `MemoryObjectSendStream.send()` gives backpressure by construction (the Twisted
  transport's `pauseProducing` is honored automatically when the buffer fills — the producer/
  consumer bridge the two flow-control models).
- Credentials/bind config are references, never inline (connectors.md §3.2).
- One package per protocol family; no monolith.

## 4. Capability catalog

| Capability | Twisted module | asyncio peer? | riko use case | Verdict |
|---|---|:--:|---|---|
| **DNS server / responder** | `twisted.names` | none (asyncio has resolvers, no server) | passive-DNS feed; dynamic/authoritative responder; service-discovery source | **Pursue** — genuinely Twisted-unique |
| **AMP typed RPC** | `twisted.protocols.amp` | none | distributed riko: worker nodes, inter-pipeline command/result RPC, backpressure-aware fan-out | **Pursue (P14 orchestration)** — Twisted-unique typed async RPC |
| **IMAP server (expose results as a mailbox)** | `twisted.mail.imap4` | none (asyncio has clients only) | present a pipeline's output as an IMAP mailbox to existing mail clients | **Niche** — only if a real "riko as mailbox" need appears |
| **Full mail store (SMTP-in + IMAP/POP3 store)** | `twisted.mail` | partial (`aiosmtpd` = SMTP-in only) | receive mail and retain/serve it, not just ingest-and-forward | **Conditional** — for *ingest only*, prefer `aiosmtpd`; use Twisted only if you need the store |
| **Custom line/binary TCP-UDP servers** | `twisted.protocols.basic` (`LineReceiver`, `IntNStringReceiver`, `NetstringReceiver`, …) | asyncio `Protocol` + `start_server` | ingest syslog, statsd, custom framed feeds as a source | **Use asyncio by default**; reach for Twisted's framers only to avoid re-implementing a fiddly framer |
| **SSH server (control/admin surface)** | `twisted.conch` (server) | `asyncssh` (server) | SSH-accessible pipeline control / exec source | **Use `asyncssh`** — asyncio peer is as good |
| **IRC server / full bot** | `twisted.words` | `bottom`/`pydle` (client/bot) | chat-ops source/sink | **Use asyncio** for bots; Twisted only for a full IRC *server* (rare) |

## 5. Prioritization — what is actually worth building

1. **`riko-amp`** (highest leverage). AMP is a typed, async, backpressure-friendly RPC with no
   asyncio equivalent. It's the natural transport for **distributed riko** (P14 orchestration):
   ship items between worker processes/nodes, carry the position envelope (§14) and delivery
   guarantee (§10). Adapting AMP over the asyncio reactor gives distributed execution without
   inventing a wire protocol.
2. **`riko-dns`** (unique, moderate use). A passive-DNS / responder source has real telemetry and
   security use cases and is impossible to build on asyncio without hand-rolling a DNS server.
3. **`riko-mail`** (conditional). Split by role: **ingest** (receive mail → Feed) is better on
   `aiosmtpd`; only the **store/serve** role (IMAP/POP3 server backed by pipeline output) justifies
   Twisted `twisted.mail`.
4. **Custom framers** — not a package; a documented recipe. When ingesting a framed TCP/UDP feed,
   default to `asyncio.start_server`; borrow a `twisted.protocols.basic` framer (bridged) only when
   the framing is genuinely fiddly and re-implementing it is the larger risk.

Deprioritized: SSH server and IRC (asyncio peers suffice); IMAP-server-as-mailbox (no demonstrated
need).

## 6. Non-goals and cautions

- **Not a reason to keep Twisted as the runtime.** Every item here is an *adapter* that bridges
  Twisted onto the asyncio loop; the engine core stays AnyIO (ROADMAP §23.1, §23 P7.6).
- **One reactor, installed once.** Two packages both installing the asyncio reactor is idempotent,
  but document the requirement and fail clearly if a different reactor is already installed.
- **Backpressure must reach the socket.** The inbound bridge must translate a full memory object
  stream into Twisted transport `pauseProducing`, or an aggressive peer can unbound memory (§22).
- **Test without the network.** Reuse the `FakeReactor`/memory-reactor pattern (already in
  `riko/bado/mock.py`) so server adapters are testable without real sockets.
- These are **shelf items** — sequence them after the runtime (P7), registry/entry-points (P8),
  and pub/sub + poll protocols (P11) exist, and only when a concrete use case lands.

## 7. Relationship to other plans

- **ROADMAP §23.1** — the runtime/protocol orthogonality principle these adapters embody.
- **connectors.md §3.1** — asyncio-native protocol clients by default; this plan is the
  server-side, Twisted-bridged complement for the capabilities with no asyncio peer.
- **orchestration.md** — `riko-amp` is a candidate transport for distributed runs.
- **P11 (`docs/REFINEMENT_PLAN.md`)** — `Publisher`/`Subscription`/poll are the interfaces every
  server adapter here implements.
