# Twisted protocol servers gameplan

## 1. Mission

Catalog the **server-side** protocol capabilities where Twisted has no real asyncio-ecosystem
equivalent, identify which would genuinely benefit riko, and define the one pattern for adapting
them: an external package that runs Twisted's protocol code on the shared asyncio loop via
`twisted.internet.asyncioreactor`, exposing a Riko `Feed` / `Publisher` / `Subscription` —
**without** Twisted being the engine's runtime (ROADMAP §23.1).

This is a *shelf* plan (like the other connector gameplans): none of it is on the core implementation
critical path. It exists so the "drop Twisted as the runtime" decision doesn't accidentally throw
away the parts of Twisted that are actually irreplaceable.

## 2. Why server-side, and why Twisted here

riko is a stream-processing engine: a source is something that **emits records over time**. On the
**client** side (poll IMAP, connect IRC, SSH-exec) asyncio-native libraries are as good or better
(`asyncssh`, `bottom`, `aioimaplib`) — use those, no Twisted. Twisted's genuine, unmatched
strength is **listening**: being a server that accepts connections and turns inbound traffic into a
stream. That maps exactly to a Riko live subscription/feed, and it is where asyncio has no
batteries-included peer.

## 3. The adaptation pattern (one shape for all of these)

```text
riko-<proto>  (external package; entry-point registered per §24)
    installs twisted.internet.asyncioreactor once for the host asyncio loop
    declares the Twisted listener/session as a Context Resource
    private execution opens the live listening port/factory handle
    each inbound message -> bounded AnyIO memory-object-stream bridge
    exposes:
        Subscription[T] / Feed source       for inbound messages
        Publisher[T]                        when the protocol supports outbound publication
```

Rules:
- The reactor is **installed, not run as a second engine runtime** — Twisted protocol callbacks use
  the host asyncio loop. Adapter startup must fail clearly if a conflicting reactor is already
  installed.
- The bounded bridge does not make Twisted flow control automatic. The adapter must explicitly
  couple a full/saturated AnyIO stream to Twisted producer `pauseProducing()` and resume it when
  capacity returns; otherwise an aggressive peer can outrun downstream consumption.
- Credentials/bind config are references, never inline (`connectors.md`).
- Immutable `Context` contains `Resource` definitions only. Live listening ports, factories,
  sessions, send/receive streams, and cleanup state are execution-owned resolved handles.
- External resources supplied with `Resource.from_external(...)` remain caller-owned; Riko never closes them.
- One package per protocol family; no monolith.

## 4. Capability catalog

| Capability | Twisted module | asyncio peer? | riko use case | Verdict |
|---|---|:--:|---|---|
| **DNS server / responder** | `twisted.names` | none (asyncio has resolvers, no server) | passive-DNS feed; dynamic/authoritative responder; service-discovery source | **Pursue** — genuinely Twisted-unique |
| **AMP typed RPC** | `twisted.protocols.amp` | none | optional distributed-driver/worker RPC, command/result transport | **Pursue conditionally** — useful only if an external distributed driver needs it |
| **IMAP server (expose results as a mailbox)** | `twisted.mail.imap4` | none (asyncio has clients only) | present a pipeline's output as an IMAP mailbox to existing mail clients | **Niche** — only if a real "riko as mailbox" need appears |
| **Full mail store (SMTP-in + IMAP/POP3 store)** | `twisted.mail` | partial (`aiosmtpd` = SMTP-in only) | receive mail and retain/serve it, not just ingest-and-forward | **Conditional** — for *ingest only*, prefer `aiosmtpd`; use Twisted only if you need the store |
| **Custom line/binary TCP-UDP servers** | `twisted.protocols.basic` (`LineReceiver`, `IntNStringReceiver`, `NetstringReceiver`, …) | asyncio `Protocol` + `start_server` | ingest syslog, statsd, custom framed feeds as a source | **Use asyncio by default**; reach for Twisted's framers only to avoid re-implementing a fiddly framer |
| **SSH server (control/admin surface)** | `twisted.conch` (server) | `asyncssh` (server) | SSH-accessible pipeline control / exec source | **Use `asyncssh`** — asyncio peer is as good |
| **IRC server / full bot** | `twisted.words` | `bottom`/`pydle` (client/bot) | chat-ops source/sink | **Use asyncio** for bots; Twisted only for a full IRC *server* (rare) |

## 5. Prioritization — what is actually worth building

1. **`riko-amp`** (conditional high leverage). AMP is typed async RPC with no direct asyncio
   equivalent. It is a candidate transport for an **optional distributed execution driver**:
   worker commands/results can carry the canonical Riko item identity/provenance and explicit
   state/artifact references without inventing a second semantic model. AMP does not become core
   Pipeline transport merely because the adapter exists.
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
  Twisted onto the asyncio loop; the engine core stays AnyIO (ROADMAP §23.1).
- **One reactor, installed once.** Adapter packages must coordinate installation and fail clearly
  if a different reactor is already installed.
- **Backpressure must reach the socket.** A bounded AnyIO queue alone is insufficient for a callback
  producer. The bridge must translate saturation into Twisted transport/producer pause and later
  resume, or an aggressive peer can create unbounded pressure upstream.
- **Test without the network.** Reuse the `FakeReactor`/memory-reactor pattern (already in
  `riko/bado/mock.py`) so server adapters are testable without real sockets.
- These are **shelf items**. Sequence them only after the common `Pipeline` execution/resource and
  `Publisher`/`Subscription` foundations they consume are available; current forward dependency
  order lives in [implementation-sequence.md](implementation-sequence.md).

## 7. Relationship to other plans

- **ROADMAP §23.1** — the runtime/protocol orthogonality principle these adapters embody.
- **execution-semantics.md** — immutable Context/resources, private execution lifecycle,
  `Feed`/`Publisher`/`Subscription`, cancellation, and backpressure semantics.
- **connectors.md** — protocol-session/resource ownership and credential references.
- **fanout-topology.md** — publication/subscription topology and branch lifecycle.
- **orchestration.md / extensibility.md E6** — an AMP adapter is only a candidate transport for an
  optional distributed driver; it does not redefine Pipeline execution.

---

> **Extracted from ROADMAP §23 (AnyIO and Twisted).** Kept here because the runtime-vs-protocol boundary and the `asyncioreactor` escape hatch are this gameplan's core rationale. `§N` references point back to [ROADMAP.md](../ROADMAP.md).

## 23. AnyIO and Twisted

> **Shipped:** see [IMPLEMENTED.md §23](../IMPLEMENTED.md#23-anyio-runtime-shipped)
> (AnyIO is the sole runtime; no Twisted; pull-based `Feed`). **Remaining:** the
> protocol-adapter design and the `asyncioreactor` escape hatch below.

AnyIO is the canonical runtime for concurrency features:

* Feed support
* task groups
* bounded memory streams
* cancellation
* timeouts
* concurrent merge
* worker coordination

**Twisted has been removed.** There is no Twisted runtime code and no
`RIKO_ASYNC_BACKEND` env var; backend selection is purely "does `anyio` import?"
(`backend = "empty" if run is None else "anyio"` in `riko/bado/__init__.py`). The
"remove or retain Twisted before 1.0" decision recorded in earlier drafts is closed — it
was removed. New runtime semantics are implemented once, on AnyIO. This does **not** ban
Twisted *protocol* implementations; see §23.1 for the runtime-vs-protocol distinction and
the `asyncioreactor` escape hatch.

`AsyncIterable` is the pipeline-level abstraction. Async iteration is pull-based (`__anext__`
is awaited by the consumer), and a `Feed` is defined by its iteration mechanism, not by
whether the source is finite or live — a `Feed` may wrap a bounded in-memory collection
just as easily as a live source.

### 23.1 Runtime and protocol layers are orthogonal

The core async **runtime** (AnyIO) and network **protocol** support are separate concerns and
must not be conflated. "Twisted is not the runtime" does **not** mean "Twisted protocols are
banned." Twisted's producer/consumer flow control and its protocol library were once reasons to
keep it as the loop; both are now covered without that coupling:

* **Flow control** — Riko uses bounded AnyIO memory streams for execution backpressure. Callback-
  driven protocol adapters such as Twisted must explicitly bridge that bounded capacity to the
  protocol's producer pause/resume mechanism; the two APIs do not couple themselves automatically.
* **Protocols** — riko ingests/emits streams, so a network protocol is a **source/sink adapter**
  (a `Feed`, `Publisher`, or `Subscription`), never a core-runtime concern. The protocol library is
  a dependency of that adapter, ideally an external package, so a new protocol is a small focused
  package rather than a core change.

Adapter library selection is on the merits, per protocol, and is mostly asyncio-native:

| Protocol | Preferred adapter library | Notes |
|---|---|---|
| SSH | `asyncssh` | asyncio-native; cleaner and better-maintained than Twisted Conch |
| SMTP | `aiosmtplib` (client) / `aiosmtpd` (server) | asyncio-native |
| IRC | `bottom` / `pydle` | asyncio-native; lighter than `twisted.words` |
| FTP/SFTP | `aioftp` / `asyncssh` (SFTP) | asyncio-native |
| XMPP | `slixmpp` | asyncio-native |
| IMAP (client/poll) | `aioimaplib` | adequate for IDLE/poll sources |

**The `asyncioreactor` escape hatch.** Where a Twisted protocol implementation is genuinely
superior — chiefly **server-side** roles and full-suite completeness (`twisted.names` DNS server,
`twisted.mail` IMAP/SMTP servers, Twisted's `AMP` RPC) — run it **on the asyncio event loop** via
`twisted.internet.asyncioreactor` **inside that one adapter package**. riko gains Twisted's
protocol strengths without Twisted being the engine's loop. See this gameplan for the server-side
capabilities worth pursuing this way.

Consequence for connectors: adapters default to asyncio-native protocol libraries and reject
Twisted *as a runtime*; a Twisted protocol *implementation* bridged via `asyncioreactor` is
permitted within an adapter when it is the superior option (almost always a server role).
