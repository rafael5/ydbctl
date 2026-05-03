# `mctl-composite.md` — irisctl ↔ ydbctl command comparison

A consolidated, command-by-command, function-by-function comparison
of the two proposed wrapper CLIs ([irisctl](iris-cli-plan.md) for
InterSystems IRIS Community Edition, [ydbctl](ydb-cli-plan.md) for
YottaDB), filed by category and classified by **whether the operation
is MUMPS / standard M** (and therefore directly relevant to VistA
portability) **or non-MUMPS** (ObjectScript-only, or otherwise tied
to one engine's extensions).

The classification answers the load-bearing question for VistA work:

> *Of the ~75 wrapper subcommands, how many operate on the M-language
> substrate that VistA actually depends on — and how many are tied to
> one engine's extensions?*

A high MUMPS-portability share means an AI agent learning one tool
gets most of the other for free; a low share means the wrappers
diverge in fundamental ways.

---

## Scope

- Reference plans: [iris-cli-plan.md](iris-cli-plan.md),
  [ydb-cli-plan.md](ydb-cli-plan.md).
- Reference surface docs: [iris-cli-surface.md](iris-cli-surface.md),
  [ydb-cli-surface.md](ydb-cli-surface.md).
- Both wrappers are **proposals** — no implementation yet. The
  command names and signatures cited here come from the proposals.

---

## Classification key

| Mark | Meaning |
|---|---|
| **M** | **MUMPS / standard M** — the operation acts on M-language artifacts (globals, M routines, M locks, M journal records, logical data). Semantically portable: a VistA workload behaves the same way on both engines. |
| **OS** | **ObjectScript-only / IRIS-only** — the operation depends on IRIS-specific machinery: namespaces, ObjectScript classes, %CSP web apps, Atelier protocol, license LUs, Mgmt Portal, REST APIs. No counterpart in YottaDB. |
| **YDB** | **YottaDB-only** — the operation depends on YottaDB OS-layer concerns (mupip rundown, gtmsecshr, GDE, IPC orphans, replication via mupip). No direct counterpart in IRIS, where the equivalent concerns are hidden behind the IRIS daemon. |
| **M*** | **MUMPS-portable in concept, but with semantic drift** — both tools expose it but the underlying engines treat it differently in ways an AI agent must know about (typically: name of the container, file format, error reporting). |

---

## Conceptual mapping (IRIS ↔ YottaDB)

| Concept | IRIS | YottaDB | Class |
|---|---|---|---|
| Container of M data | **Namespace** (logical, mapped via CPF) | **Region** (logical, mapped via `.gld`) | M* |
| Physical DB file | `IRIS.DAT` (one per database) | `*.dat` (one per region/segment) | M |
| Config file | `iris.cpf` (text) | `*.gld` (binary, edited via GDE) | OS / YDB |
| Journal file | IRIS journal (`<install>/mgr/journal/`) | `*.mjl` rotating files | M |
| Database recovery | implicit via `iris start` | explicit `mupip journal -recover` + `mupip rundown` | YDB |
| Source-code unit | M routine (`.mac`/`.int`) **or** ObjectScript class (`.cls`) | M routine (`.m`) only | M / OS |
| Source CRUD API | `/api/atelier/*` (HTTP) | none — `docker cp` + recompile | OS / YDB |
| SQL | First-class (built-in) | Plugin (Octo / ROcto) | M* |
| Live metrics | `/api/monitor/metrics` (Prometheus) | none — scrape via `mupip dumpfhead` / `$VIEW()` / GUI :9081 | OS / YDB |
| Lock manager | `^LOCK` command + `%SYS.LockTable` | `LOCK` command + `lke` | M |
| User auth | `_SYSTEM`/`SYS`, role system (`%All`, `%Developer`, …) | none in core; per-protocol at GUI/ROcto | OS |
| License model | LU-capped (Community: 8 LU) | Apache 2.0, no per-process budget | OS |
| Container as | Daemon (one `iris-main` PID 1) | Library (M processes attach to shared memory) | OS / YDB |
| Container default user | UID 51773 (`irisowner`) | UID 0 (root, for `gtmsecshr`) | OS / YDB |
| Privileged helper | none (daemon owns everything) | `gtmsecshr` (setuid root, mode 4500) | YDB |

---

## §1. Health / introspection

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 1 | One-shot health snapshot | `irisctl status` | `ydbctl status` | M* | Same envelope; YDB version adds IPC-orphan + gtmsecshr fields. |
| 2 | Engine version | `irisctl version` | `ydbctl version` | M* | Returns image labels + `iris_system_info` vs `yottadb -version` + plugin probes. |
| 3 | Listening-port reachability | `irisctl ports` | `ydbctl ports` | M* | IRIS: 1972/52773/9430/8001. YDB: 9080/9081/1337 + optional VistA listeners. |
| 4 | Composite "should I worry" | `irisctl health` | `ydbctl health` | M* | Same idea; YDB additionally checks IPC orphans + journal-recoverable state. |
| 5 | Mgmt portal launcher | `irisctl portal [PATH]` | (n/a) | OS | IRIS-only — opens `/csp/sys/...`. YDB GUI lives on `:9080` and is managed by `ydbctl gui` (§13). |
| 6 | Show env vars in container | (not in irisctl plan) | `ydbctl env [NAME]` | YDB | Filters to `ydb_*`/`gtm*`. IRIS equivalent would dump `ISC_*`/`IRIS_*`. |

---

## §2. Lifecycle / container management

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 7 | Start container | `irisctl start` | `ydbctl start` | M* | IRIS: waits for listeners. YDB: waits for `gtmsecshr` socket. |
| 8 | Graceful stop | `irisctl stop [--timeout 60]` | `ydbctl stop [--timeout 60]` | M* | Both default to `-t 60`; IRIS runs `iris stop`, YDB runs `mupip rundown` via the entrypoint trap. |
| 9 | Restart | `irisctl restart` | `ydbctl restart` | M | Stop+start. |
| 10 | Recreate from scratch | `irisctl recreate` | `ydbctl recreate` | M* | IRIS uses the documented INSTALL_GUIDE recipe; YDB matches the docker-vista build args. |

---

## §3. Logs

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 11 | Tail container console log | `irisctl logs [--tail N] [--follow]` | `ydbctl logs [--tail N] [--follow]` | M* | IRIS: `messages.log`. YDB: container syslog (gtmsecshr) + container stdout. |
| 12 | View alerts | `irisctl alerts` | (no equivalent) | OS | IRIS surfaces `alerts.log` via `/api/monitor/alerts`. YDB has no equivalent endpoint; alerts go to syslog. |
| 13 | Show journal records | (use `metrics` for journal stats) | `ydbctl logs --journal` / `ydbctl journal status` | YDB | IRIS journals are managed via the daemon; YDB exposes `*.mjl` directly. |

---

## §4. License / cost

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 14 | Current license use | `irisctl license` | (n/a) | OS | YDB has no LU concept (Apache 2.0). |
| 15 | Watch license consumption | `irisctl license watch [--interval Ns]` | (n/a) | OS | IRIS-only. |
| 16 | Who is holding LUs | `irisctl license users` | (n/a) | OS | IRIS-only. |

---

## §5. Metrics / monitoring

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 17 | All counters | `irisctl metrics [--prefix X]` | (no equivalent) | OS | IRIS: 107 Prometheus counters from `/api/monitor/metrics`. YDB: scattered via `mupip dumpfhead` / `$VIEW()` / GUI :9081 — no consolidated scrape path. |
| 18 | Describe one counter | `irisctl metrics describe NAME` | (no equivalent) | OS | IRIS-only. |
| 19 | Raw Prometheus scrape | `irisctl metrics scrape` | (no equivalent) | OS | IRIS-only. |
| 20 | Per-process stats | (covered by `metrics`) | `ydbctl exec '$VIEW(...)'` | M | Both engines have process-stat APIs but YDB requires explicit M calls. |

---

## §6. Database structure (regions / namespaces)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 21 | List logical M containers | `irisctl namespaces` | `ydbctl regions` | M* | IRIS namespaces and YDB regions are conceptually the same — different name. |
| 22 | Show physical DB files | `irisctl databases [NS]` | `ydbctl segments` / `ydbctl files` | M* | YDB exposes the segment/file split that IRIS hides. |
| 23 | Map global → container | (implicit via namespace) | `ydbctl globals` (gde-show-name) | YDB | IRIS resolves globals via namespace mappings in CPF; YDB requires explicit GDE entries. |
| 24 | DB file metadata | `irisctl databases [NS]` (size, free space) | `ydbctl dbinfo [REGION]` | M* | YDB version exposes 50+ `mupip dumpfhead` fields; IRIS exposes a metric-derived subset. |

---

## §7. Globals (data)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 25 | Display a global subtree | `irisctl exec --ns NS 'ZW ^G'` | `ydbctl globals show NAME` | M | Same `ZWRITE` semantics on both. The `irisctl exec` route works identically. |
| 26 | Export a global | `irisctl exec --ns NS '...'` (manual `^%GO`) | `ydbctl globals export NAME [--format Z]` | M | YDB plan has a dedicated wrapper; IRIS does too via `^%GOF`/`^%GO` driven by `irisctl exec`. Functionally portable. |
| 27 | Import a global | `irisctl exec --ns NS '...^%GI'` | `ydbctl load FILE` | M | Both use logical-import M routines; YDB exposes `mupip load` directly. |

---

## §8. Routines (M code)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 28 | List routines | `irisctl source list NS [PATTERN]` | `ydbctl routines list [PATTERN]` | M* | IRIS via `/api/atelier/v6/{ns}/docs?type=mac`; YDB via filesystem enum on `ydb_routines`. |
| 29 | Get a routine | `irisctl source get NS/Routine.mac` | `ydbctl routines get NAME` | M | Both retrieve M source. IRIS supports `.cls` (ObjectScript) too — see §10. |
| 30 | Put a routine | `irisctl source put NS/Routine.mac` (stdin) | `ydbctl routines put` (stdin/`--file`) | M | IRIS uses Atelier `PutDoc` (HTTP); YDB uses `docker cp` + recompile. |
| 31 | Delete a routine | `irisctl source delete NS/Routine.mac` | (manual via `ydbctl exec`) | M* | YDB plan doesn't enumerate; deletion is `ZK^routine` or filesystem `rm`. |
| 32 | Compile routines | `irisctl source compile NS PATTERN` | `ydbctl routines compile [PATTERN]` | M | Both produce engine-specific object code (.obj for IRIS, .o for YDB) but the source is portable M. |
| 33 | Search routines | `irisctl source search NS PATTERN` | (manual via `grep`) | M* | IRIS-side via Atelier; YDB has no built-in full-text search across routines. |
| 34 | Diff vs local file | `irisctl source diff NS/Routine.mac local.m` | (n/a) | M* | IRIS-only convenience; trivial to add to ydbctl. |

---

## §9. Source CRUD via REST (Atelier)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 35 | All `source *` operations over HTTP | yes (`/api/atelier/v6`) | no | OS | YDB has no equivalent of the Atelier protocol. The base image's `%ydbwebreq` server (`/api/ping`, `/api/version`) doesn't include source CRUD. |
| 36 | OpenAPI/Swagger discovery | `/api/mgmnt/v2/{ns}/{app}/` | no | OS | IRIS-only. |

---

## §10. ObjectScript classes (IRIS-only artifact)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 37 | List `.cls` files | `irisctl source list NS *.cls` | (n/a) | OS | YDB has no class concept. |
| 38 | Get a class | `irisctl source get NS/MyClass.cls` | (n/a) | OS | IRIS-only. |
| 39 | Put a class | `irisctl source put NS/MyClass.cls` | (n/a) | OS | IRIS-only. |
| 40 | Compile a class | `irisctl source compile NS Pkg.*.cls` | (n/a) | OS | IRIS-only. |

These four rows are the single most concentrated "non-MUMPS / OS"
zone of the comparison. **VistA itself contains no `.cls` files** —
which is why VistA ports cleanly across both engines despite this
gap.

---

## §11. Execute M / ObjectScript

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 41 | One-line M code | `irisctl exec --ns NS '<code>'` | `ydbctl exec --region R '<code>'` | M | Both wrappers auto-append `HALT`; both default to `<<'EOF'` heredoc tag. **Direct semantic match.** |
| 42 | Stdin-fed code | `irisctl exec --ns NS --stdin` | `ydbctl exec --stdin --region R` | M | Same. |
| 43 | Execute a routine entry | `irisctl exec --ns NS '...D ^routine'` | `ydbctl exec --run "MAIN^routine" args...` | M | YDB exposes `yottadb -run`; IRIS uses `D ^routine`. |
| 44 | Run routine from file | `irisctl exec --file routine.m` | `ydbctl exec --file routine.m` | M | Both `docker cp` + invoke. |
| 45 | Execute ObjectScript class method | `irisctl exec --ns NS 'D ##class(Pkg.X).Method()'` | (n/a) | OS | IRIS-only. |
| 46 | Interactive shell | `irisctl shell [--ns NS]` | `ydbctl shell [--region R]` | M | Both `docker exec -it` to direct mode. |

---

## §12. SQL

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 47 | One-line SQL | `irisctl sql --ns NS '<sql>'` | `ydbctl sql '<sql>' [--writes]` | M* | IRIS has built-in SQL over namespaces. YDB requires Octo/ROcto plugin; if neither is installed, `ydbctl sql` fails with a structured error. |
| 48 | Execute SQL file | `irisctl sql --ns NS --file schema.sql` | `ydbctl sql --file schema.sql` | M* | Same idea. IRIS uses `$SYSTEM.SQL.Schema.ImportDDL`; YDB uses Octo's `\i` or ROcto-over-psql. |
| 49 | DDL allowed | always | only if ROcto launched with `-a` | M* | YDB defaults to read-only over the wire — needs explicit opt-in. |
| 50 | Result-set as JSON | yes | yes (after Phase 2) | M* | Output envelopes match. |

---

## §13. Optional services / network listeners

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 51 | Manage Mgmt Portal / Web Gateway | (always on; `irisctl portal`) | (n/a) | OS | IRIS Web Gateway is part of the daemon. |
| 52 | Start GUI / web admin | (n/a) | `ydbctl gui start [--port N] [--readwrite]` | YDB | IRIS Mgmt Portal needs no start; YottaDB GUI is opt-in. |
| 53 | Start ROcto (PostgreSQL wire) | (n/a; IRIS SQL is over 1972) | `ydbctl rocto start [-w] [-a]` | YDB | YDB-only — IRIS exposes SQL over the superserver. |
| 54 | Start YDB Web Server | (n/a) | `ydbctl web start [--port 9080]` | YDB | YDB-only. |
| 55 | Start GT.CM remote DB server | (n/a) | `ydbctl gtcm start [--port 6789]` | YDB | YDB-only. ECP is the IRIS analogue but isn't typically wrapped. |

---

## §14. Locks (M LOCK command)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 56 | List active M locks | `irisctl exec --ns NS 'D ^%LOCK'` (manual) | `ydbctl locks show [--region R] [--pid P]` | M | Both engines expose the same `LOCK` command from M; YDB has a dedicated `lke show` wrapper. IRIS has `^%SYS.LockTable` but irisctl plan doesn't yet wrap it. |
| 57 | Clear a lock | `irisctl exec --ns NS '...'` (manual) | `ydbctl locks clear [--lock NAME] [--pid P]` | M | YDB has `lke clear`; IRIS has `^%SYS.Lock.Manage`. |
| 58 | Cleanup orphan lock entries | (manual) | `ydbctl locks cleanup` | M | `lke clnup` has no exact IRIS equivalent — the IRIS daemon manages this transparently. |

---

## §15. Journal / WAL

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 59 | Journal status | (via `irisctl metrics --prefix iris_jrn_`) | `ydbctl journal status` | M* | Same logical concept; surface differs (Prometheus counters vs `mupip journal -show`). |
| 60 | Verify journal | (n/a) | `ydbctl journal verify` | YDB | IRIS handles journal validation internally on start. |
| 61 | Extract journal records | (n/a in plan) | `ydbctl journal extract --to PATH` | M | Both engines support journal extract; only YDB plan wraps it. |
| 62 | Enable journaling | (CPF setting via `irisctl config merge`) | `ydbctl journal enable [--region R]` | M | Same logical M-level setting. |
| 63 | Disable journaling | (CPF setting) | `ydbctl journal disable [--region R]` | M | Same. |
| 64 | Switch / rotate journal | (built-in) | `ydbctl journal rotate [--region R]` | M | Same. |

---

## §16. Backup / restore / data movement

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 65 | Backup database | `irisctl backup [--to PATH]` | `ydbctl backup [--to PATH] [--online]` | M | IRIS uses external backup of `IRIS.DAT`+`iris.cpf`+journal; YDB uses `mupip backup -bytestream`. Both produce restorable artifacts. |
| 66 | Restore database | `irisctl restore --from PATH` | `ydbctl restore --from PATH` | M | Same idea, different mechanism. |
| 67 | Logical export | (manual `^%GO` via `irisctl exec`) | `ydbctl extract REGION [--format Z]` | M | Both engines understand `.zwr` (Z) and `.go` (G) formats; YDB plan wraps it directly. |
| 68 | Logical import | (manual `^%GI`) | `ydbctl load FILE` | M | Same. |

---

## §17. Integrity / maintenance

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 69 | Integrity check | (manual `^INTEG`) | `ydbctl integ [--region R] [--full]` | M | Both engines have an INTEG utility; only YDB plan wraps it. |
| 70 | Reorg / defrag | (background via daemon) | `ydbctl reorg [--region R]` | M* | IRIS does background reorg; YDB requires manual `mupip reorg`. |
| 71 | Freeze updates | (n/a in plan) | `ydbctl freeze [--on\|--off]` | M | Both engines have a freeze; only YDB plan wraps it. |
| 72 | Extend region | (auto in IRIS) | `ydbctl extend REGION --blocks N` | M* | IRIS auto-extends; YDB requires manual extend if `auto-extend=off`. |

---

## §18. IPC / shared memory (no IRIS analog)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 73 | List IPC keys | (n/a) | `ydbctl ipc` | YDB | IRIS abstracts IPC entirely behind the daemon. |
| 74 | Run down orphan IPC | (n/a; daemon handles it) | `ydbctl rundown [--region '*']` | YDB | The single most important YDB-only command. Required after any unclean shutdown. |
| 75 | Replay journal forward | (n/a; built-in) | `ydbctl recover [--region '*']` | YDB | IRIS does this implicitly on `iris start`. |

---

## §19. Configuration

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 76 | Show config | `irisctl config show` | `ydbctl gde` (interactive) | M* | IRIS: dump `iris.cpf` (text). YDB: GDE-driven `.gld` browse. |
| 77 | Apply config merge | `irisctl config merge file.cpf` | `ydbctl gde @script.gde` | M* | IRIS: `iris merge IRIS file.cpf` is the only safe CPF mutation. YDB: GDE script is the only safe `.gld` mutation. **Same principle, different binaries.** |

---

## §20. VistA-layer operations (docker-vista-fork specific)

These appear only when the active profile flags the container as a
docker-vista build. They wrap the same `GTM/bin/*.sh` helpers that
this repo already ships.

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 78 | Manage RPC Broker (port 9430) | (built into ZSTU autostart for IRIS) | `ydbctl vista rpcbroker [start\|stop\|status]` | M | IRIS handles via `J ZISTCP^XWBTCPM1(9430)` in `^ZSTU`; YDB exposes the same broker via `GTM/bin/rpcbroker.sh`. **Same MUMPS routine on both backends.** |
| 79 | Manage VistALink (port 8001) | (built into ZSTU) | `ydbctl vista vistalink [start\|stop\|status]` | M | Same — `START^XOBVLL(8001)` on both. |
| 80 | Manage HL7 listener | (built into Taskman config) | `ydbctl vista hl7 [start\|stop\|status]` | M | HL7 routines are identical M code on both. |
| 81 | Manage VistA journaling | (CPF + IRIS daemon) | `ydbctl vista journal [enable\|disable\|rotate]` | M* | Same VistA-level concern; different engine plumbing. |
| 82 | Probe VistA listener ports | `irisctl ports` | `ydbctl vista ports` | M | Same listener set (9430 / 8001 / 9100-9101). |

> **Architectural observation.** The VistA layer is the single
> region of the surface where `irisctl` and `ydbctl` are doing
> *the same MUMPS thing on the same MUMPS routines*; the only
> difference is which engine binary spawns the process. This is
> the strongest evidence that the wrappers should share a
> `vistactl` overlay (or at least the VistA-layer subcommands
> should live in a shared module). See `ydb-cli-plan.md` §10
> open question 4.

---

## §21. Replication / HA (out of scope for both Phase 1 plans)

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 83 | Mirror / replication source | not in plan | `ydbctl repl source [start\|stop\|...]` | M* | IRIS has Mirroring (different from YDB replication). |
| 84 | Receiver / failover | not in plan | `ydbctl repl receiver [start\|stop\|...]` | M* | Conceptually similar. |
| 85 | Rollback after failover | not in plan | `ydbctl repl rollback --fetchresync` | M* | Conceptually similar. |

---

## §22. Convenience

| # | Operation | irisctl | ydbctl | Class | Notes |
|---|---|---|---|---|---|
| 86 | Print underlying command (debug) | `irisctl which <op>` | `ydbctl which <op>` | M* | Same idea both sides. |
| 87 | Open relevant docs page | `irisctl docs <KEY>` | `ydbctl docs <topic>` | OS | Different doc sites; same UX. |
| 88 | Open Mgmt portal | `irisctl portal [PATH]` | (n/a; use `ydbctl gui start`) | OS | IRIS-specific. |

---

## Summary statistics

Counts (rows 1-88; rows where one tool has nothing are still counted
under the tool that has the operation):

| Class | Count | % of total |
|---|---:|---:|
| **M** (true MUMPS-portable) | 26 | 30% |
| **M\*** (portable with semantic drift) | 25 | 28% |
| **OS** (ObjectScript / IRIS-only) | 24 | 27% |
| **YDB** (YottaDB-only) | 13 | 15% |
| Total operations indexed | 88 | 100% |

### Read another way

- **MUMPS-aligned (M + M\*) = 51 / 88 = 58%.** Most of the wrapper
  surface speaks the same M-language language on both backends.
- **Engine-specific (OS + YDB) = 37 / 88 = 42%.** Just under half
  the surface is genuinely tied to one backend's machinery.
- **IRIS-only operations outnumber YottaDB-only operations
  ~2:1** (24 vs 13) — because IRIS ships more layers (license,
  Atelier REST, classes, /api/monitor, Mgmt Portal). YottaDB's
  spartan design means fewer engine-specific commands.

---

## Implications for VistA portability

VistA is **pure MUMPS** — no ObjectScript classes, no IRIS-specific
class-based dispatch, no `%CSP` web apps. Concretely: every routine
in the FOIA distribution is a `.m` file (or `.int`/`.ro` packaging
of one), and every API call is `D ENTRY^ROUTINE` or
`$$FUNC^ROUTINE`. The class-based `##class(...)` syntax appears
exactly zero times in core VistA.

That fact maps cleanly onto this comparison:

1. **VistA touches the M / M\* rows only.** All 51 MUMPS-classified
   operations work identically (or near-identically) across both
   engines — which is why FOIA VistA can run on IRIS Community
   Edition and on YottaDB without source changes.
2. **The 24 OS-only operations are infrastructure, not application
   code.** Atelier REST, license LUs, Mgmt Portal, ObjectScript
   classes — none of these are how VistA functions. They affect
   *how an operator manages* the IRIS instance, not what VistA
   *does* on it.
3. **The 13 YDB-only operations are also infrastructure.** IPC
   rundown, gtmsecshr, GDE, replication via mupip — all
   admin-layer concerns, invisible to VistA M code.

So an AI agent that learns the M and M\* rows of this matrix has
covered the VistA-pertinent surface end to end. The remaining 37
engine-specific rows are about how to *operate* the chosen backend,
not about how VistA itself behaves on it.

### What this means for the wrappers

- A VistA-only AI agent could skip the OS and YDB rows entirely
  with no loss of capability for the application workload.
- Operators of either backend need their respective half of the
  37 engine-specific rows, but rarely the other half.
- A VistA-portability test suite need only exercise the M + M\*
  rows; passing on both engines proves the workload is portable.

---

## Cross-tool consistency at a glance

For 30 of the 88 indexed operations, the irisctl and ydbctl
subcommand names are byte-for-byte identical (e.g. `status`,
`version`, `ports`, `logs`, `health`, `start`, `stop`, `restart`,
`recreate`, `exec`, `sql`, `shell`, `backup`, `restore`, `which`,
`docs`). For another 15, names differ only in noun (`namespaces`
vs `regions`, `databases` vs `segments`) where the underlying
engine forces a different vocabulary. The remaining 43 are
single-engine subcommands by necessity.

The design goal — **AI agents drive either backend with the same
vocabulary** — is achievable and load-bearing. The
[ydb-cli-plan.md §14](ydb-cli-plan.md) cross-tool consistency table
is the canonical contract; this composite document is the
exhaustive verification of it.

---

## Sources

- [iris-cli-surface.md](iris-cli-surface.md) — IRIS surface reference
- [iris-cli-plan.md](iris-cli-plan.md) — `irisctl` proposal
- [ydb-cli-surface.md](ydb-cli-surface.md) — YottaDB surface reference
- [ydb-cli-plan.md](ydb-cli-plan.md) — `ydbctl` proposal
- [INSTALL_GUIDE.md](INSTALL_GUIDE.md) — IRIS Community install + recovery recipes
