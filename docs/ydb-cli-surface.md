# YottaDB Docker Container — CLI / API Surface Reference

A comprehensive map of every way to drive a YottaDB Docker container
programmatically. Compiled from the official docs at docs.yottadb.com
(Administration & Operations Guide, Programmers Guide, MUPIP, GDE, LKE,
DSE references), the YottaDB GitLab/GitHub repos, and the official
images on Docker Hub.

The intended audience is humans and AI agents who need a single
authoritative reference of which tools, flags, ports, files, and
environment variables exist — and how they fit together — without
re-discovering the surface on every task.

Companion document: [iris-cli-surface.md](iris-cli-surface.md).
Where YottaDB diverges from IRIS conventions, this doc calls it out.

> **Live source of truth.** Every binary in `$ydb_dist/` accepts
> `-help`. When in doubt, run e.g. `mupip help backup` inside the
> running container — it overrides anything below.

---

## Scope

| Item | Value |
|---|---|
| Reference image | `yottadb/yottadb-base` (alias `yottadb/yottadb`) on Docker Hub |
| Variants | `yottadb/yottadb-debian` (Debian-slim + Octo + GUI + bindings, ~803 MB), `yottadb/yottadb-debug-base` (debug+ASAN) |
| Reference YottaDB version | r2.02 / r2.04 (both current stable) |
| Default install root | `/usr/local/lib/yottadb/r2NN/` = `$ydb_dist` |
| Container default user | **root** (UID 0) — required for `gtmsecshr` setuid model |
| Container ENTRYPOINT | `/docker-main-startup.sh` — sources `ydb_env_set`, runs recovery + journaling, starts CMD or shell, traps `mupip rundown -region '*'` on shutdown |
| Default workdir | `/data` (env `gtmdir=/data` baked in; intended bind-mount target) |
| Default CMD | shell (no IRIS-style daemon — see Gotcha #1) |
| Exposed ports | 9080 (web/GUI), 9081 (GUI stats) |
| License model | none — Apache 2.0; no LU concept |

> **Architectural note vs IRIS.** YottaDB is a **library**, not a
> daemon. There is no central server process to "start the database";
> M processes open `.dat` files via mmap + System V IPC directly.
> `mupip rundown` after a crash is mandatory because there is no
> supervising daemon to clean up. This shapes everything below.

---

## 1. Container entrypoint — `docker-main-startup.sh`

The entrypoint is a shell script that runs **as root** because
`gtmsecshr` is setuid-root. Its responsibilities:

1. `source $ydb_dist/ydb_env_set` — exports all `ydb_*` vars and
   creates `~/.yottadb/r2NN_<arch>/` with a default `.gld` + `.dat`
   if no DB exists at `gtmdir`/`ydb_dir`.
2. `mupip journal -recover -backward "*.mjl"` — replay/rollback
   journals on any region whose last shutdown was unclean.
3. `mupip rundown -region "*"` — release any leftover IPC from
   prior crashed containers.
4. `exec` the supplied CMD (interactive shell by default, or a user
   command — typically `yottadb -direct` or `yottadb -run %ydbgui`).
5. On `SIGTERM`/`SIGINT`: trap → `mupip rundown -region "*"` → exit.

**There is no IRIS-style `iris-main` flag surface** (`--check-caps`,
`--key`, `--before`, `--after`, `--password-file`). YottaDB's
container has no license to install, no password file convention,
and no built-in pre/post-startup hook flags. Customization happens
by:

| Want to do | How |
|---|---|
| Pre-start setup | Bake into the Dockerfile, or override the entrypoint |
| Post-start data load | Pass a `CMD` that runs your loader before exec'ing the shell |
| Pass a config file | Bind-mount it; reference via `ydb_routines` / `ydb_gbldir` |
| Set passwords | Set `ydb_passwd` env to the obfuscated keyring value |

### Container shutdown safety

| Action | Outcome |
|---|---|
| `docker stop` (sends SIGTERM, waits) | Clean. Trap runs `mupip rundown`, releases IPC, exits 0. |
| `docker stop -t 1` (1-sec timeout) | **Risky** — rundown may not finish; next start needs a manual rundown. |
| `docker kill` (SIGKILL) | **Leaks IPC.** Manual `mupip rundown -region '*'` required next start. Bind-mounted DB survives, IPC keys do not. |

---

## 2. Environment variables

YottaDB has ~80 env vars. The high-impact ones grouped here; full
list in the [Basic Operations doc](https://docs.yottadb.com/AdminOpsGuide/basicops.html).
Almost every `ydb_*` var has a legacy `gtm*` alias still honored
(e.g. `ydb_routines` ↔ `gtmroutines`, `ydb_gbldir` ↔ `gtmgbldir`).

### Critical (every process touches these)

| Variable | Purpose | Default | Gotcha |
|---|---|---|---|
| `ydb_dist` | YDB install root | auto-detected from `argv[0]` | **Setting wrong is worse than unset** — binary infers from its own path. Don't override. |
| `ydb_dir` | User's YDB working dir (where `ydb_env_set` builds defaults) | `$HOME/.yottadb` (or `gtmdir` if set) | In the container `gtmdir=/data`. |
| `ydb_routines` (`gtmroutines`) | M routine search path; `*` enables auto-relink | `$ydb_dist/libyottadbutil.so` | **Defaults to a `.so`, not a directory.** Replacing it with a clean dir breaks GDE/%GO/%GI/%D — the utility routines are packaged into `libyottadbutil.so`. |
| `ydb_gbldir` (`gtmgbldir`) | Path to global directory `.gld` | none | If unset, every YDB process errors on first global access. |
| `ydb_chset` | `M` (8-bit) or `UTF-8` mode | `M` | Switching changes which `*.o` cache is used (`utf8/`). |
| `ydb_icu_version` | ICU library major version | autodetect | Container bakes `74`. |

### Files / paths

| Variable | Purpose | Default |
|---|---|---|
| `ydb_tmp` | Temp + `gtmsecshr` socket dir | `/tmp` |
| `ydb_log` | Log dir (now mostly syslog) | `/tmp` |
| `ydb_logdir` | Per-process log dir | `$ydb_log` |
| `ydb_baktmpdir` | Backup temp space | backup dest or `/tmp` |
| `ydb_snaptmpdir` | INTEG snapshot space | cwd |
| `ydb_linktmpdir` | Auto-relink ctl-files | `$ydb_tmp` |
| `ydb_statsdir` | Per-process statistics | `$ydb_tmp` |
| `ydb_retention` | Days to keep old journals/tmp | 42 |

### Security / encryption

| Variable | Purpose | Gotcha |
|---|---|---|
| `ydb_passwd` | Obfuscated GPG passphrase for encrypted DB | Empty string = prompt; unset = no encryption attempted; literal cleartext is **unsupported**. |
| `ydb_random_passwd` | Generate a random per-process key | helper only |
| `ydb_obfuscation_key` | File whose hash obfuscates `ydb_passwd` | — |
| `ydb_crypt_config` | Encryption + TLS config file | shared with replication & ROcto |
| `ydb_crypt_plugin` | Plugin path under `$ydb_dist/plugin` | — |
| `ydb_crypt_fips` | FIPS-mode bool | — |
| `ydb_tls_passwd_<label>` | TLS cert passphrase per-label | one var per label |

### Compilation / runtime

| Variable | Purpose | Default |
|---|---|---|
| `ydb_compile` | Initial `$ZCOMPILE` | — |
| `ydb_boolean` | 0=short-circuit, 1=full, 2=full+warn | 0 |
| `ydb_side_effects` | 0=trad, 1=L→R, 2=L→R+warn | 0 |
| `ydb_noundef` | `""` for undefined vs error | error |
| `ydb_recompile_newer_src` | Recompile if `.m` newer than `.o` | — |
| `ydb_link` | `RECURSIVE`/`NORECURSIVE` | NORECURSIVE |

### Direct-mode / I/O

| Variable | Purpose | Default |
|---|---|---|
| `ydb_prompt` | Direct-mode prompt | `YDB>` |
| `ydb_principal` | Override `$PRINCIPAL` | tty |
| `ydb_principal_editing` | colon-list of `$PRINCIPAL` deviceparams | none |
| `ydb_readline` | Use GNU readline | true (via `ydb_env_set`) |
| `ydb_lvnullsubs` | 0=NEVER, 1=ALWAYS, 2=EXISTING | 2 |
| `ydb_nocenable` | Ignore Ctrl-C on `$PRINCIPAL` | 0 |
| `ydb_quiet_halt` | Suppress FORCEDHALT | 0 |

### Memory / stack

| Variable | Range | Default |
|---|---|---|
| `ydb_mstack_size` (KiB) | 25..10000 | 272 |
| `ydb_mstack_crit_threshold` (%) | 15..95 | 90 |
| `ydb_malloc_limit` (per-proc cap) | 0=unlimited | 0 |
| `ydb_max_storalloc` | unlimited | unlimited |
| `ydb_string_pool_limit` | unlimited | unlimited |

### Error / debug

`ydb_etrap`, `ydb_ztrap_form`, `ydb_zyerror`, `ydb_ztrap_new`,
`ydb_zstep`, `ydb_zinterrupt`, `ydb_dbglvl`, `ydb_coredump_filter`,
`ydb_procstuckexec`, `ydb_msgprefix` (`YDB` or `GTM`).

### Replication

`ydb_repl_instance`, `ydb_repl_instname`, `ydb_repl_instsecondary`,
`ydb_repl_filter_timeout` (default 64s), `ydb_mupjnl_parallel`,
`ydb_custom_errors`.

### External calls / call-in

`ydb_ci` (`GTMCI`) — call-in table for C→M;
`ydb_xc_<package>` — external call table per package;
`ydb_cm_<node-name>` — GT.CM client → server endpoint.

### Database / journal

`ydb_db_create_ver` (set `6`/`V6` for V6-compatible files),
`ydb_db_startup_max_wait`, `ydb_error_on_jnl_file_lost`,
`ydb_jnl_release_timeout` (300s), `ydb_extract_nocol`.

### Auto-relink

`ydb_autorelink_shm` (MiB), `ydb_autorelink_ctlmax` (1k..16M, def 50k),
`ydb_autorelink_keeprtn`.

### Container-image-baked defaults

| Variable | Value |
|---|---|
| `gtmdir` | `/data` |
| `LC_ALL` | `C.UTF-8` |
| `ydb_icu_version` | `74` |
| `EDITOR` | `/usr/bin/nano` |
| `WORKDIR` | `/data` |

---

## 3. The YottaDB binary suite

All under `$ydb_dist/` (= `/usr/local/lib/yottadb/r2NN/`).

### 3.1 Core engine + shells

| Binary | Purpose | Top flags / subcommands | Mutating | DB state |
|---|---|---|---|---|
| `yottadb` | M language runtime; direct mode REPL; runs M routines | `-direct`, `-run <entryref>`, `-help`, `-version` | varies | either |
| `mumps` | Symlink to `yottadb` (legacy GT.M name) | same | varies | either |
| `ydb` | Shell wrapper: sources `ydb_env_set`, runs recovery + journaling, exec's `mumps`, `mupip rundown` on exit | `-direct`, `-run`, pass-through | yes (rundowns) | either |
| `ydb_env_set` | Sourced shell file: exports all `ydb_*` vars; seeds default DB | `source $ydb_dist/ydb_env_set` | yes (creates files) | n/a |
| `ydb_env_unset` | Reverses `ydb_env_set` | `source ydb_env_unset` | no | n/a |

### 3.2 Admin utilities

| Binary | Purpose |
|---|---|
| `mupip` | Multi-Purpose Interchange Program — primary admin tool; 25+ subcommands (§4) |
| `gde` | Global Directory Editor — alias for `mumps -run GDE`. Edits `.gld` files. |
| `dse` | Database Structure Editor — expert-only block-level surgery; can corrupt a DB in one keystroke |
| `lke` | M Lock Editor — view/clear active M locks |
| `gtmsecshr` | setuid-root helper daemon — auto-spawned; never invoked directly |

### 3.3 Network listeners (optional, separate launches)

| Binary | Purpose | Default port |
|---|---|---|
| `gtcm_gnp_server` | GT.CM remote-database server (TCP) | none defined; `-service=` (commonly 6789) |
| `mupip replicate -source -start` | Replication source server | user-chosen `-PORT=` |
| `mupip replicate -receiver -start` | Replication receiver | user-chosen `-LISTENPORT=` |

### 3.4 Plugins

Located at `$ydb_dist/plugin/bin/` (when installed):

| Binary | Purpose | Default port | Invocation |
|---|---|---|---|
| `octo` | Interactive SQL CLI over YottaDB globals | — (TTY) | `$ydb_dist/plugin/bin/octo` |
| `rocto` | "Remote Octo" — PostgreSQL wire-protocol server | **1337** (override `-p`) | `rocto [-w] [-a] [-p N]`. `-w` allow writes, `-a` allow DDL — both off by default |
| `%ydbwebreq` (M routine) | Forking HTTP server — base of GUI | **9080** | `yottadb -run start^%ydbwebreq` |
| `%ydbgui` (M routine) | Web management GUI | **9080** main, 9081 stats | `yottadb -run %ydbgui [--port N] [--readwrite] [--tlsconfig name] [--auth-file users.json] [--gzip] [--log 0..3]` |

Library plugins (no CLI):
- **YDBPosix** — POSIX wrappers callable from M
- **YDBAIM** — Application Independent Metadata; in-memory cross-references
- **YDBEncrypt / YDBzlib** — encryption/compression shims

### 3.5 Installer

| Binary | Purpose | Top flags |
|---|---|---|
| `ydbinstall` | Installer (in distro tarball) | `--installdir`, `--utf8`, `--user`, `--group`, `--overwrite-existing`, `--octo`, `--posix`, `--aim`, `--encplugin`, `--zlib`, `--allplugins`, `--verbose` |
| `ydbinstall.sh` | Bootstrap installer; auto-detects distro, downloads tarball, invokes `ydbinstall` | same |

### 3.6 Deprecated / legacy

| Binary | Status | Replacement |
|---|---|---|
| `ftok` | Deprecated standalone | `mupip ftok` |
| `semstat2` | Deprecated standalone | `ipcs(1)` + `mupip rundown` |
| `dbcertify` | Marginal in r2.x — pre-V5→V6 upgrade only | n/a |
| `mubclnup` | Cleans up MUPIP BACKUP temp files left by aborted backups | rarely user-facing |

---

## 4. MUPIP subcommand inventory

`mupip <subcommand> [qualifiers]`. The single most important admin
binary in YottaDB. Source:
[Database Management Tool (MUPIP)](https://docs.yottadb.com/AdminOpsGuide/dbmgmt.html).

### 4.1 Database lifecycle

| Subcommand | Purpose | Key qualifiers | Mutating | DB state |
|---|---|---|---|---|
| `CREATE` | Create `.dat` files from `.gld` | `-REGION`, `-V6`/`-NOV6` | yes | quiesced |
| `EXTEND` | Grow a region | `-BLOCKS`, `-REGION` | yes | open |
| `SET` | Mutate region/file/journal characteristics | `-JOURNAL=`, `-ACCESS_METHOD=`, `-FLUSH_TIME=`, `-LOCK_SPACE=`, `-RESERVED_BYTES=`, `-DEFER_TIME=`, `-NULL_SUBSCRIPTS=`, `-EPOCHTAPER`, `-INST_FREEZE_ON_ERROR`, `-PARTIAL_RECOV_BYPASS`, … (40+ params) | yes | mostly quiesced |
| `SIZE` | Estimate growth | `-HEURISTIC=`, `-ADJACENCY=`, `-SELECT=`, `-REGION` | no | open |
| `UPGRADE` | Bump on-disk file format | — | yes | quiesced |
| `DOWNGRADE` | Demote to older file-header format | — | yes | quiesced |
| `ENDIANCVT` | Convert big↔little endian | `-OVERRIDE`, `-OUTDB` | yes | quiesced |

### 4.2 Backup / restore / data movement

| Subcommand | Purpose | Key qualifiers | Mutating | DB state |
|---|---|---|---|---|
| `BACKUP` | Backup database | `-BYTESTREAM`, `-DATABASE`, `-ONLINE`/`-NOONLINE`, `-SINCE`, `-TRANSACTION`, `-NEWJNLFILES` | yes | online OR quiesced |
| `RESTORE` | Restore bytestream backup | `-EXTEND`, `-NETTIMEOUT` | yes | quiesced (target absent) |
| `EXTRACT` | Logical export to flat file | `-FORMAT={B\|G\|Z}`, `-FREEZE`, `-SELECT`, `-REGION`, `-STDOUT`, `-LABEL`, `-OCHSET`, `-NULL_IV` | no | open (FREEZE optional) |
| `LOAD` | Logical import | `-FORMAT`, `-BEGIN`, `-END`, `-FILLFACTOR`, `-ONERROR={STOP\|PROCEED\|INTERACTIVE}`, `-IGNORECHSET` | yes | open |

### 4.3 Integrity / maintenance

| Subcommand | Purpose | Key qualifiers | Mutating |
|---|---|---|---|
| `INTEG` | Integrity check | `-FAST`, `-FULL`, `-ONLINE`/`-NOONLINE`, `-FILE`, `-REGION`, `-BLOCK`, `-MAP`, `-TRANSACTION`, `-BRIEF`, `-KEYRANGES`, `-ADJACENCY`, `-TN_RESET` | no |
| `REORG` | Defragment / coalesce blocks | `-FILL_FACTOR`, `-EXCLUDE`, `-NOCOALESCE`, `-REGION`, `-RESUME`, `-TRUNCATE`, `-UPGRADE`, `-DOWNGRADE`, `-INDEX_FILL_FACTOR` | yes |
| `DUMPFHEAD` | Dump file header | `-FILE`, `-REGION`, `-FLUSH` | no |
| `HASH` | MurmurHash3 of source files | filename arg | no |
| `RCTLDUMP` | Dump relinkctl file contents | `-RELINKCTL` | no |
| `TRIGGER` | Manage M triggers | `-TRIGGERFILE=`, `-SELECT=`, `-UPGRADE`, `-STDIN`, `-STDOUT`, `-NOPROMPT` | yes |

### 4.4 Process / IPC control

| Subcommand | Purpose | Mutating |
|---|---|---|
| `RUNDOWN` | Release shared mem/IPC for orphaned regions. `-FILE`, `-REGION='*'`, `-OVERRIDE`, `-RELINKCTL`. **The recovery-after-crash command.** | yes |
| `FREEZE` | Suspend updates (logical or hard). `-ON`, `-OFF`, `-ONLINE`, `-RECORD`, `-OVERRIDE` | yes |
| `INTRPT` | Send `MUPIP INTRPT` signal to PID | n/a |
| `STOP` | Send shutdown signal to PID | n/a |
| `SEMAPHORE` | Inspect/release IPC semaphores. `-RELEASE` | yes |
| `FTOK` | Show IPC keys for a file/pool. `-DB`, `-JNLPOOL`, `-RECVPOOL`, `-ID`, `-ONLY`, `-NOHEADER` | no |
| `EXIT` | Quit MUPIP shell | — |

### 4.5 Journal

`mupip journal -<action> [direction] [filters] <jnl-file>`

| Action | Purpose | Type |
|---|---|---|
| `-EXTRACT[=file]` | Dump journal records to text/M format | read |
| `-RECOVER` | Forward/backward replay (non-replicated) | mutating |
| `-ROLLBACK` | Roll back replicated DBs to known sync point | mutating |
| `-SHOW` | Report on journal contents/metadata | read |
| `-VERIFY` | Validate journal integrity | read |

Direction & filters: `-FORWARD`/`-BACKWARD`, `-AFTER`/`-BEFORE`/`-SINCE`,
`-FETCHRESYNC=port`, `-RESYNC=jnlseqno`, `-LOOKBACK_LIMIT`,
`-APPLY_AFTER_IMAGE`, `-BROKENTRANS=`, `-LOSTTRANS=`, `-CHAIN`,
`-CHECKTN`, `-ERRORLIMIT=n`, `-FENCES=`, `-FULL`, `-INTERACTIVE`,
`-PARALLEL[=n]`, `-REDIRECT=`, `-GLOBAL=`, `-ID=`, `-TRANSACTION=`,
`-USER=`.

### 4.6 Replication

`mupip replicate -<role> -<action> [tuning]`

| Role + action | Purpose |
|---|---|
| `-SOURCE -START` | Start source server (transmits journal records over TCP) |
| `-SOURCE -SHUTDOWN` | Stop source server |
| `-SOURCE -ACTIVATE` / `-DEACTIVATE` | Toggle active/passive |
| `-SOURCE -CHECKHEALTH` | Probe source server |
| `-SOURCE -CHANGELOG` | Rotate log file/level |
| `-SOURCE -SHOWBACKLOG` | Report unconsumed records |
| `-RECEIVER -START` | Start receiver server (TCP listener) |
| `-RECEIVER -SHUTDOWN` | Stop receiver |
| `-RECEIVER -CHECKHEALTH` | Probe receiver |
| `-INSTANCE -CREATE` | Initialize replication-instance file |
| `-EDITINSTANCE` | Edit replication-instance attributes |
| `-ROLLBACK -FETCHRESYNC` | Sync after primary failure |

Tuning: `-CONNECTPARAMS=`, `-TLSID=`, `-PLAINTEXTFALLBACK`,
`-RENEGOTIATE_INTERVAL=`, `-SENDBUFFSIZE=`, `-RECVBUFFSIZE=`,
`-HELPERS=m,n`. Bootstrap: `-UPDATERESYNC=`, `-NORESYNC`,
`-INITIALIZE`. Roles: `-UPDOK`/`-UPDNOTOK`, `-ROOTPRIMARY`,
`-PROPAGATEPRIMARY`.

---

## 5. GDE — Global Directory Editor

Run as `gde` or `mumps -run GDE`. Edits the binary `.gld` file
that maps M global names → regions → segments → `.dat` files.

| Command | Purpose |
|---|---|
| `ADD` | Add a name/region/segment/template entry |
| `CHANGE` | Modify an existing entry |
| `DELETE` | Remove an entry |
| `SHOW` | Print current GDE state |
| `VERIFY` | Sanity-check the directory |
| `EXIT` / `QUIT` | Save and quit / discard and quit |
| `RENAME` | Rename a region/segment |
| `SETGD` | Switch to a different `.gld` |
| `TEMPLATE` | Manage templates (default settings for new regions) |
| `LOCKS` | Configure lock space |
| `LOG` | Set log destination |
| `@<file>` | Replay commands from a file (script mode) |

> GDE is the **only** supported way to mutate `.gld` files. Editing
> `.gld` with anything else corrupts the directory.

---

## 6. LKE — M Lock Editor

`lke <command> [qualifiers]`. View and clear active M locks.

| Command | Purpose |
|---|---|
| `SHOW` | Display active locks. `-ALL`, `-LOCK=`, `-PID=`, `-REGION=`, `-WAIT`, `-INTERACTIVE`, `-OUTPUT=` |
| `CLEAR` | Clear locks. Same qualifiers as `SHOW`; `-INTERACTIVE` for confirmation |
| `CLNUP` | Clean up orphan lock entries |
| `SPAWN` | Spawn a sub-shell |
| `EXIT` / `HELP` | Standard |

---

## 7. DSE — Database Structure Editor

**Expert-only.** Operates on raw GDS blocks. Commands like
`OVERWRITE`, `ADD`, `REMOVE`, `SHIFT` can corrupt a database in
one keystroke. The docs explicitly warn to consult YottaDB
support before any mutating command.

| Read-only commands | Mutating commands |
|---|---|
| `DUMP`, `FIND`, `RANGE`, `INTEGRIT`, `EVALUATE`, `CACHE`, `OPEN`, `CLOSE`, `PAGE` | `ADD`, `CHANGE`, `OVERWRITE`, `RESTORE`, `REMOVE`, `SHIFT`, `MAPS`, `WCINIT`, `BUFFER_FLUSH`, `CRITICAL`, `ALL` |

---

## 8. Network protocol surface

Unlike IRIS — which runs a Superserver on 1972 and a Web Gateway on
52773 by default — **vanilla YottaDB has no network listener at all**
out of the box. Every "network surface" below is an opt-in,
separately-launched process.

| Surface | Listener? | Default port | Protocol | Invocation |
|---|---|---|---|---|
| Base YottaDB engine | **No** — local-only IPC (shared memory + semaphores + Unix-domain socket to gtmsecshr) | — | — | — |
| `gtmsecshr` | yes (Unix-domain socket only, in `$ydb_tmp`) | — | proprietary IPC | auto-launched |
| **GT.CM** server | yes (TCP) | none defined; `-service=` (commonly 6789) | proprietary GNP | `$ydb_dist/gtcm_gnp_server -log=GTCM.log -service=6789` |
| **MUPIP REPLICATE source** | yes (TCP) | user-chosen `-PORT=` | proprietary | `mupip replicate -source -start -port=N` |
| **MUPIP REPLICATE receiver** | yes (TCP) | user-chosen `-LISTENPORT=` | proprietary | `mupip replicate -receiver -start -listenport=N` |
| **YDBOcto / `octo`** | no (CLI only) | — | — | `$ydb_dist/plugin/bin/octo` |
| **ROcto** | yes | **1337** | PostgreSQL wire protocol (psql, JDBC, ODBC, DBeaver) | `$ydb_dist/plugin/bin/rocto [-w] [-a] [-p N]` |
| **YDB Web Server** | yes (forking HTTP) | **9080** | HTTP/HTTPS | `yottadb -run start^%ydbwebreq` |
| **YDB GUI** | yes | **9080** main, 9081 stats | HTTP/HTTPS | `yottadb -run %ydbgui` |
| Telnet | not present | — | — | — |
| SSH | not present | — | — | use `docker exec` |

### YDB Web Server permanent endpoints

When `%ydbwebreq` or `%ydbgui` is running on 9080:

| Endpoint | Purpose |
|---|---|
| `GET /api/ping` | Liveness probe |
| `GET /api/version` | YottaDB + plugin versions |
| `GET /api/auth-mode` | Authentication mode in effect |
| `POST /api/login` | Establish session |
| `POST /api/logout` | End session |
| `GET /api/...` (user-defined) | Routes declared in `_ydbweburl.m` |

> **No equivalent of `/api/monitor/metrics`.** YottaDB ships no
> Prometheus-style metrics endpoint. Operators scrape via
> `mupip replicate -checkhealth` / `-showbacklog`,
> `dse dump -fileheader`, `$VIEW()`, `$ZPEEK`/`%PEEKBYNAME`,
> stats-share files (`ydb_statsdir`), and syslog `YDB-{I/W/E/F}-`
> messages. The GUI surfaces some of these on port 9081 but
> there's no documented machine-parseable scrape path.

### Default credentials

YottaDB has **no built-in user database**. Authentication is delegated:

| Surface | Auth mechanism |
|---|---|
| Database access | POSIX file perms on `.dat` / `.gld` / `.mjl` |
| ROcto | optional username/password file via `-a` flag (and TLS via `ydb_crypt_config`) |
| YDB GUI | `--auth-file users.json` (bcrypt hashes) |
| GT.CM | none — TCP source IP filtering only |

---

## 9. Filesystem surface inside the container

| Path / extension | Contents |
|---|---|
| `$ydb_dist` (= `/usr/local/lib/yottadb/r2NN/`) | Install root: binaries, `.so`, `plugin/`, `gtmsecshrdir/`, `ydb_env_set`, GDE script, default `.gld` |
| `$ydb_dist/gtmsecshrdir/gtmsecshr` | setuid-root helper (mode 4500) |
| `$ydb_dist/plugin/bin/` | Plugin binaries: `octo`, `rocto` |
| `$ydb_dist/plugin/o/`, `$ydb_dist/plugin/r/` | Plugin object/M routines (POSIX, AIM, GUI, web) |
| `$ydb_dist/utf8/` | UTF-8 mode object library mirror |
| `/data/` (= `gtmdir`) | Default working dir (intended bind-mount target) |
| `*.gld` (default `yottadb.gld`; legacy `mumps.gld`) | **Global Directory** — binary file mapping global names → regions → segments → `.dat` files |
| `*.dat` | **GDS database file** — 4 KiB header + B-tree blocks (default 4 KiB block size) + master/local bitmaps |
| `*.mjl` | Active journal file; lives in same FS as its `.dat` |
| `*.mjl_YYYYJJJHHMMSS` | Rotated journal (Julian-day suffix); collision suffix `_0`, `_1`, … |
| `*.repl` | Replication instance file (header + 16 source-server slots + history) |
| `*.m` | M source |
| `*.o` | Compiled M object (per-version, ABI-compatible only within major) |
| `relinkctl-*` | Auto-relink control files in `$ydb_linktmpdir` |
| `$ydb_tmp/gtm_secshr*` socket | Unix-domain socket gtmsecshr listens on |
| `*.mje`, `*.mjo` | stderr/stdout from M processes started via `JOB` |
| `YDB_FATAL_ERROR.ZSHOW_DMP_*.txt` | Auto-dump on abnormal termination |

---

## 10. Permissions / security

| Concern | Convention |
|---|---|
| Database access | Pure POSIX file perms on `.dat` / `.gld` / `.mjl`; **no RDBMS-style GRANT system** |
| Default UID inside container | **root (UID 0)** |
| `gtmsecshr` | Owned root, mode 4500 (setuid root, executable only by owner). Wrapper scrubs all env vars except `ydb_dist`, `ydb_dbglvl`, `ydb_log`, `ydb_tmp` before exec'ing the daemon. Auto-shuts-down after 60 min idle. Communicates only via Unix-domain socket in `$ydb_tmp`. Logs to syslog `LOG_USER` with `GTMSECSHR` facility. |
| What runs as root | **Only `gtmsecshr`.** Every other YDB process runs as the calling user. |
| Honest-processes assumption | Read-only processes still need RW on shared-memory; integrity assumes M-language processes don't poke shm directly |
| TLS | Replication, ROcto, GUI, and Web all consume `ydb_crypt_config` for `tls:` blocks; per-label password via `ydb_tls_passwd_<label>` |
| Encrypted DB | Plugin-based (`gpgagent`, `libgcrypt`, OpenSSL); `ydb_passwd` set from obfuscated keyring |

---

## 11. The docker-vista-fork YottaDB layer

This repo's YottaDB path is **VistA-on-YottaDB**, not vanilla
YottaDB. Selected via `--build-arg flags="-y …"` to the top-level
`Dockerfile`. The wrapping layer adds:

| Component | Purpose |
|---|---|
| `GTM/install.sh` | Wraps `ydbinstall`. Default `-v r2.02`. `-y` selects YottaDB (vs GT.M); `-r` install from source; `-s` skip shared-mem tuning. |
| `Common/ovydbPostInstall.sh` | Trivial post-install hook (currently just removes Dashboard). |
| `GTM/createVistaInstance.sh` | Creates `/home/<instance>/` with FOIA VistA loaded into `.dat` files. |
| `GTM/importVistA.sh` | Loads FOIA VistA routines + globals into the YottaDB instance. |
| `GTM/installOcto.sh` | Optional: install Octo (SQL plugin). |
| `GTM/installYottaDBGUI.sh` | Optional: install the YottaDB GUI plugin. |
| `GTM/bin/rpcbroker.sh` | Start VistA RPC Broker (port 9430). |
| `GTM/bin/vistalink.sh` | Start VistALink listener (port 8001). |
| `GTM/bin/hl7.sh` | Start HL7 listener. |
| `GTM/bin/enableJournal.sh` / `disableJournal.sh` / `rotateJournal.sh` | Journaling helpers wrapping `mupip set` / `mupip rundown`. |
| `GTM/bin/cia.sh`, `bmxnet.sh`, `fixHL7Port.sh` | Misc operational helpers. |
| Dockerfile entrypoint | `${entry_path}/bin/start.sh` (built into `/home/<instance>/bin/` at install time). |
| Exposed ports | 22 (SSH), 8001 (VistALink), 9100/9101 (HL7), 9430 (RPC Broker), 8080/8081/8089/9080 (web/GUI), 5001, 57772, 61012 |

The autoInstaller flags for FOIA-on-YottaDB are
`-y -b -e -m -p ./Common/ovydbPostInstall.sh`:
- `-y` install YottaDB (vs GT.M)
- `-b` build/bootstrap
- `-e` enable journals
- `-m` install M routines (FOIA VistA)
- `-p <script>` post-install hook

Operational note: the `GTM/bin/*.sh` scripts run inside the container
as root. They mostly wrap `mupip` / `lke` / direct M routine
invocations.

---

## 12. Common patterns for programmatic interaction

### 12.1 One-shot M routine via direct mode

```sh
docker exec -i ydb yottadb -direct <<'END'
ZN "USER"
WRITE $ZV,!
HALT
END
```

`HALT` (or `H`) terminates the M process; `QUIT` only exits the
current stack frame.

### 12.2 Run a labelled entry

```sh
docker exec ydb yottadb -run "MAIN^myroutine"
```

Or with arguments:

```sh
docker exec ydb yottadb -run "PROCESS^foo" arg1 arg2
```

### 12.3 SQL via Octo

```sh
docker exec -i ydb sh -c "$ydb_dist/plugin/bin/octo" <<'END'
SELECT * FROM Patient LIMIT 10;
END
```

### 12.4 SQL via ROcto from outside the container

If `rocto` is running on container port 1337, mapped to host 1337:

```sh
psql -h localhost -p 1337 -U yottadb yottadb -c 'SELECT version();'
```

Use any PostgreSQL-protocol client.

### 12.5 Backup

```sh
docker exec ydb mupip backup -bytestream -online "*" /backup/
```

### 12.6 Recover from unclean shutdown

```sh
docker exec ydb mupip journal -recover -backward "*.mjl"
docker exec ydb mupip rundown -region "*"
```

### 12.7 Inspect file header (no running process required)

```sh
docker exec ydb mupip dumpfhead -file /data/yottadb.dat
```

### 12.8 Stats via `$VIEW()` (the closest YottaDB has to metrics)

```sh
docker exec -i ydb yottadb -direct <<'END'
W $VIEW("DBFLUSH"),!
W $VIEW("GVSTAT"),!
HALT
END
```

For richer stats, enable `ydb_statshare` and read the per-process
files in `$ydb_statsdir`.

### 12.9 Read mode-700 host volumes

When the container writes its `/data` to a host-mounted directory
owned by root, host-side reads via root helper:

```sh
docker run --rm --user 0 -v ~/data/ydb:/data:ro alpine \
    ls -lh /data/
```

### 12.10 Inspect the image without starting YottaDB

```sh
docker run --rm --entrypoint sh yottadb/yottadb-base -c \
    'ls /usr/local/lib/yottadb/r202/'
```

Skips `docker-main-startup.sh`, so no recovery, no rundown trap,
no IPC allocation.

---

## 13. Gotchas

1. **YottaDB is a library, not a daemon.** No central server to
   "start". M processes open `.dat` files directly. After any
   crash, `mupip rundown -region "*"` is mandatory before next use.
2. **`gtmsecshr` is the only setuid component.** Not a network
   daemon. Auto-spawned. Killing it is safe — next M process
   re-spawns it. If `mupip rundown` complains about IPC keys, it's
   gtmsecshr you need.
3. **`ydb_dist` is auto-detected from `argv[0]`.** Setting it
   wrong is worse than leaving it unset. Don't override.
4. **`ydb_routines` defaults to a `.so`, not a directory.** YDB's
   utility routines (`%GO`, `%GI`, `GDE`, `%D`, etc.) are packaged
   into `libyottadbutil.so`. Replacing `ydb_routines` with a clean
   dir breaks GDE.
5. **Auto-relink (`*` in `ydb_routines`) is stateful.** Allocates
   SHM up to `ydb_autorelink_shm` MiB and creates `relinkctl-*`
   files in `$ydb_linktmpdir`. These accumulate; `mupip rundown` is
   the only clean teardown.
6. **No built-in metrics endpoint** like IRIS's
   `/api/monitor/metrics`. Closest equivalent is `ydb_statshare`
   shared statistics surfaced by the GUI on port 9081.
7. **Default port collisions:** GUI 9080 + stats 9081, ROcto 1337,
   Web 9080 (same as GUI). If you start both `%ydbgui` and
   `%ydbwebreq` you must override `--port` on one — they share the
   underlying web-server engine.
8. **Octo is opt-in.** No SQL unless `ydbinstall --octo` ran.
   ROcto needs `-w` to allow writes and `-a` to allow DDL — both
   off by default.
9. **Replication ports are not fixed.** Source/receiver listen on
   whatever you pass `-PORT=` / `-LISTENPORT=`. No well-known-port
   convention.
10. **`mupip rundown -region "*"` is the safe blanket form.** Using
    only `-file` and missing one leaves IPC orphaned.
11. **Endianness matters at the file level.** A `.dat` from a
    big-endian box won't open on x86-64 — must `mupip endiancvt`
    first. Only portable cross-platform format is logical
    `mupip extract`.
12. **Journal file rotation.** A new `.mjl` rotates at size limit
    or on switch; the previous file is renamed
    `*.mjl_<julian-stamp>`. Backup tools must follow rotations.
13. **`mumps.gld` is the legacy GT.M name.** YottaDB ships
    `yottadb.gld` by default; both names work because GDE follows
    `ydb_gbldir` / `gtmgbldir`.
14. **`ydb_passwd` empty-string vs unset are different.** Empty =
    prompt interactively; unset = no encryption attempted. Literal
    cleartext is unsupported.
15. **`docker stop -t 10` may be too short.** The shutdown trap
    runs `mupip rundown -region "*"`; on a busy DB this can take
    longer than 10s. Prefer `docker stop -t 60` minimum.
16. **`docker kill` leaks IPC.** SIGKILL bypasses the trap; manual
    `mupip rundown` is needed before next start. Bind-mounted DB
    survives, IPC keys do not.
17. **`ftok` and `semstat2` standalone binaries are deprecated.**
    Use `mupip ftok` and `ipcs(1)` + `mupip rundown`.
18. **DSE is the closest thing to "single-user mode + raw block
    editor."** Can corrupt a DB beyond recovery in one keystroke.
19. **`gtmprofile` / `ydb_env_set` mutates your shell**, including
    BOTH the `ydb_*` and the legacy `gtm*` aliases. This can
    collide with parallel GT.M installs.
20. **Different YDB versions need separate `ydb_tmp` and
    `ydb_log`.** They will fight over gtmsecshr socket names
    otherwise.
21. **`mupip integ -online` can lie under heavy update load.** Use
    `-noonline` (which requires standalone access) for forensic
    checks.
22. **No license / LU concept.** Unlike IRIS Community's 8-LU cap,
    YottaDB is Apache 2.0 with no per-process license budget.
23. **Container runs as root.** Required by gtmsecshr setuid model.
    Hardening Kubernetes `securityContext: runAsNonRoot: true`
    breaks YottaDB. Mitigation: build a custom image with a fixed
    non-root user that owns `gtmsecshrdir`; specifics outside the
    base image's documented support.

---

## Sources

### Official YottaDB documentation

- [Administration & Operations Guide TOC](https://docs.yottadb.com/AdminOpsGuide/index.html)
- [Basic Operations (env vars, binaries)](https://docs.yottadb.com/AdminOpsGuide/basicops.html)
- [Database Management (MUPIP)](https://docs.yottadb.com/AdminOpsGuide/dbmgmt.html)
- [GDE — Global Directory Editor](https://docs.yottadb.com/AdminOpsGuide/gde.html)
- [DSE — Database Structure Editor](https://docs.yottadb.com/AdminOpsGuide/dse.html)
- [LKE / M Locks](https://docs.yottadb.com/AdminOpsGuide/mlocks.html)
- [Journaling](https://docs.yottadb.com/AdminOpsGuide/ydbjournal.html)
- [Replication](https://docs.yottadb.com/AdminOpsGuide/dbrepl.html)
- [GDS file format](https://docs.yottadb.com/AdminOpsGuide/gds.html)
- [GT.CM remote DB](https://docs.yottadb.com/AdminOpsGuide/gtcm.html)
- [IPC Resources](https://docs.yottadb.com/AdminOpsGuide/ipcresource.html)
- [Monitoring](https://docs.yottadb.com/AdminOpsGuide/monitoring.html)
- [Security Philosophy](https://docs.yottadb.com/AdminOpsGuide/securityph.html)
- [Containers](https://docs.yottadb.com/AdminOpsGuide/containers.html)
- [Installing](https://docs.yottadb.com/AdminOpsGuide/installydb.html)
- [Encryption](https://docs.yottadb.com/AdminOpsGuide/encryption.html)
- [Programmer's Guide — Utility Routines](https://docs.yottadb.com/ProgrammersGuide/utility.html)
- [Octo Intro](https://docs.yottadb.com/Octo/intro.html)
- [ROcto](https://docs.yottadb.com/Octo/rocto.html)
- [YDB Web Server](https://docs.yottadb.com/Plugins/ydbwebserver.html)
- [YDBGUI](https://gitlab.com/YottaDB/UI/YDBGUI)

### Docker / packaging

- [yottadb-base on Docker Hub](https://hub.docker.com/r/yottadb/yottadb-base)
- [yottadb-debian on Docker Hub](https://hub.docker.com/r/yottadb/yottadb-debian)
- [YDB Dockerfile (GitHub)](https://github.com/YottaDB/YDB/blob/master/Dockerfile)
- [YDB issue #126 — `ydb` script behavior](https://github.com/YottaDB/YDB/issues/126)
- [YDB issue #209 — env var semantics](https://github.com/YottaDB/YDB/issues/209)

### docker-vista-fork local layer

`GTM/install.sh`, `GTM/bin/*.sh`, `Common/ovydbPostInstall.sh` —
the FOIA-VistA-on-YottaDB build wrappers in this repository.
