"""jobcut CLI — `jobcut <command>`.

Commands (PLAN §3): init | pull | score | surface | market | dashboard.
Some are functional (ported scripts); some are Phase 1 stubs that say so.
"""

from __future__ import annotations

import argparse
import sys


def _todo(name: str) -> int:
    print(f"`jobcut {name}` is not implemented yet (Phase 1). See docs/archive/fase-2-restructure/plan.md.")
    return 1


def _copy_if_absent(src_text: str, dest, label: str) -> None:
    if dest.exists():
        print(f"  · {label}: already exists, kept ({dest})")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src_text)
    print(f"  ✓ {label}: created {dest}")


def cmd_init(args) -> int:
    """Set up a data dir: .env, profile.md, config/, searches/ from bundled templates."""
    import sys
    from importlib import resources
    from . import paths

    data = paths.data_dir()
    data.mkdir(parents=True, exist_ok=True)
    print(f"Setting up jobcut in: {data}\n")
    tpl = resources.files("jobcut") / "templates"

    # .env (token)
    env = data / ".env"
    if env.exists():
        print(f"  · .env: already exists, kept ({env})")
    else:
        token = ""
        if sys.stdin.isatty() and not args.no_input:
            token = input("  Apify API token (Enter to fill in later): ").strip()
        env.write_text(f"APIFY_TOKEN={token or 'apify_api_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}\n")
        print(f"  ✓ .env: created {env}" + ("" if token else "  (edit it to add your APIFY_TOKEN)"))

    _copy_if_absent((tpl / "profile.example.md").read_text(), data / "profile.md", "profile.md")
    _copy_if_absent((tpl / "config.example.json").read_text(), data / "config" / "config.json", "config/config.json")
    _copy_if_absent((tpl / "taxonomy.example.json").read_text(), data / "config" / "taxonomy.json", "config/taxonomy.json")
    for f in (tpl / "searches").iterdir():
        _copy_if_absent(f.read_text(), data / "searches" / f.name, f"searches/{f.name}")

    print(
        "\nNext steps:\n"
        "  1. Edit .env with your Apify token.\n"
        "  2. Edit profile.md (your roles, skills, dealbreakers — drives scoring).\n"
        "  3. Edit config/config.json (your geography under \"routing\").\n"
        "  4. Edit searches/*.json (titles + locations); the example-*.json are samples.\n"
        "  5. Try it:  jobcut pull --read   (free; or `jobcut pull` for a paid scrape)\n"
        "             jobcut score && jobcut surface && jobcut market\n"
        "  6. Schedule it daily — see scheduler/ templates.\n"
    )
    return 0


def cmd_pull(args) -> int:
    from . import pull
    pull.main(["--read"] if args.read else [])
    return 0


def cmd_score(args) -> int:
    from . import score
    score.run()
    return 0


def cmd_ingest_scores(args) -> int:
    """Upsert scores from a JSON file (e.g. produced by a Claude/Cowork scoring skill)."""
    from . import ingest
    try:
        summary = ingest.ingest_scores(args.json, backend=args.backend)
    except FileNotFoundError:
        print(f"ingest-scores: file not found: {args.json}")
        return 1
    except ValueError as exc:  # bad JSON or wrong shape (JSONDecodeError is a ValueError)
        print(f"ingest-scores: invalid scores file ({exc})")
        return 1
    msg = f"ingest-scores · wrote {summary['ingested']} scores"
    if summary["skipped"]:
        msg += f", skipped {summary['skipped']} invalid"
    if summary["unknown_job_ids"]:
        msg += f", {len(summary['unknown_job_ids'])} job_id(s) not in the jobs table"
    print(msg)
    for err in summary["errors"]:
        print(f"  · skipped: {err}")
    return 0


def cmd_ingest_profile(args) -> int:
    """Build profile.md + the skills kit from a structured JSON (an interview or CV extraction)."""
    from . import ingest
    try:
        s = ingest.ingest_profile(args.json)
    except FileNotFoundError:
        print(f"ingest-profile: file not found: {args.json}")
        return 1
    except ValueError as exc:  # bad JSON or wrong shape
        print(f"ingest-profile: invalid profile file ({exc})")
        return 1
    print(f"ingest-profile · profile.md written · {s['skills']} skills "
          f"({s['have']} have / {s['partial']} partial / {s['gap']} gap); kit re-derived")
    return 0


def cmd_ingest_salary(args) -> int:
    """Upsert salary estimates from a JSON file (e.g. produced by a Claude/Cowork salary skill)."""
    from . import ingest
    try:
        summary = ingest.ingest_salary(args.json)
    except FileNotFoundError:
        print(f"ingest-salary: file not found: {args.json}")
        return 1
    except ValueError as exc:  # bad JSON or wrong shape (JSONDecodeError is a ValueError)
        print(f"ingest-salary: invalid estimates file ({exc})")
        return 1
    msg = f"ingest-salary · wrote {summary['ingested']} estimate(s)"
    if summary["skipped"]:
        msg += f", skipped {summary['skipped']} invalid"
    if summary["unknown_job_ids"]:
        msg += f", {len(summary['unknown_job_ids'])} job_id(s) not in the jobs table"
    print(msg)
    for err in summary["errors"]:
        print(f"  · skipped: {err}")
    return 0


def cmd_ingest_events(args) -> int:
    """Apply application write-ops from a JSON file (e.g. a Claude/Cowork tracking skill)."""
    from . import ingest
    try:
        summary = ingest.ingest_events(args.json)
    except FileNotFoundError:
        print(f"ingest-events: file not found: {args.json}")
        return 1
    except ValueError as exc:  # bad JSON or wrong shape (JSONDecodeError is a ValueError)
        print(f"ingest-events: invalid events file ({exc})")
        return 1
    msg = f"ingest-events · wrote {summary['written']} update(s)"
    if summary["skipped"]:
        msg += f", skipped {summary['skipped']} invalid"
    if summary["unknown_job_ids"]:
        msg += f", {len(summary['unknown_job_ids'])} job_id(s) not in the jobs table"
    print(msg)
    for err in summary["errors"]:
        print(f"  · skipped: {err}")
    return 0


def cmd_ingest_documents(args) -> int:
    """Ingest prep/debrief/study documents from a JSON file (e.g. a Claude/Cowork prep skill)."""
    from . import ingest
    try:
        summary = ingest.ingest_documents(args.json)
    except FileNotFoundError:
        print(f"ingest-documents: file not found: {args.json}")
        return 1
    except ValueError as exc:  # bad JSON or wrong shape (JSONDecodeError is a ValueError)
        print(f"ingest-documents: invalid documents file ({exc})")
        return 1
    msg = f"ingest-documents · wrote {summary['written']} document(s)"
    if summary["archived"]:
        msg += f", archived {summary['archived']}"
    if summary["skipped"]:
        msg += f", skipped {summary['skipped']} invalid"
    if summary["unknown_job_ids"]:
        msg += f", {len(summary['unknown_job_ids'])} job_id(s) not in the jobs table"
    print(msg)
    for err in summary["errors"]:
        print(f"  · skipped: {err}")
    return 0


def cmd_import_docs(args) -> int:
    """Import prep documents from the documents/ drop-folder (B-22). A markdown file with a
    `jobcut:` frontmatter block is resolved to its application and upserted via the same
    path as `ingest-documents` (idempotent by client_key). `--dry-run` shows the plan only.
    """
    from . import docsinbox, paths
    root = args.dir or str(paths.documents_dir())
    docsinbox.ensure_dir(root)

    if getattr(args, "dry_run", False):
        from . import db
        conn = db.connect()
        try:
            docs, reports = docsinbox.scan(root, conn)
        finally:
            conn.close()
        print(f"import-docs (dry-run) · {len(docs)} document(s) would be written from {root}")
        for r in reports:
            if r["status"] == "ignored":
                continue
            extra = f" → {r['detail']}" if r.get("detail") else ""
            print(f"  [{r['status']}] {r['file']}{extra}")
        return 0

    s = docsinbox.import_dir(root)
    print(f"import-docs · wrote {s['written']} document(s) from {root}")
    if s["offer_level"]:
        print(f"  {s['offer_level']} left offer-level (round not uniquely resolved)")
    if s["skipped"]:
        print(f"  skipped {s['skipped']}:")
        for e in s["errors"]:
            print(f"  · {e}")
    return 0


def cmd_import_jobs(args) -> int:
    """Upsert scraped job rows from a JSON file (flattened or nested actor format)."""
    from . import ingest
    try:
        summary = ingest.import_jobs(args.json)
    except FileNotFoundError:
        print(f"import-jobs: file not found: {args.json}")
        return 1
    except ValueError as exc:  # bad JSON or wrong shape (JSONDecodeError is a ValueError)
        print(f"import-jobs: invalid jobs file ({exc})")
        return 1
    print(f"import-jobs · new {summary['new']}, updated {summary['updated']}, "
          f"skipped {summary['skipped']} (deduped), invalid {summary['invalid']}")
    return 0


def cmd_add_job(args) -> int:
    """Add a job manually (by URL or fields); optionally link an application."""
    from . import db, ingest

    fields = {}
    for key in ("url", "company", "title", "location", "description"):
        val = getattr(args, key, "") or ""
        if val:
            fields[key] = val
    if args.job_id:
        fields["job_id"] = args.job_id

    conn = db.connect()
    try:
        try:
            result = ingest.add_job(fields, conn)
        except ValueError as exc:
            print(f"add-job: {exc}")
            return 1
        jid = result["job_id"]
        verb = "created" if result["created"] else "updated"
        msg = f"add-job · {verb} job {jid}"
        if args.apply is not None:
            status = args.apply if isinstance(args.apply, str) else "applied"
            db.set_application_status(conn, jid, status, source="manual")
            msg += f" · linked application ({status})"
        print(msg)
        return 0
    finally:
        conn.close()


def cmd_unscored(args) -> int:
    """List hireable jobs that still need a score (read-only; for an external scorer)."""
    from . import db, filter as _filter
    raw_ids = getattr(args, "ids", None)
    ids = None
    if raw_ids and raw_ids.strip():
        ids = [i for i in raw_ids.replace(",", " ").split() if i]
    include_scored = getattr(args, "include_scored", False)
    needs_backend = getattr(args, "needs_backend", None)
    conn = db.connect()
    try:
        rows = _filter.unscored(conn, include_scored=include_scored, ids=ids,
                                needs_backend=needs_backend)
    finally:
        conn.close()
    if getattr(args, "json", False):
        import json
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    elif ids:
        print(f"unscored · {len(rows)} job(s) for the given ids (use --json for the data)")
    elif needs_backend:
        print(f"unscored · {len(rows)} hireable job(s) not yet scored by {needs_backend} "
              f"(rule_based floor counts as unscored; use --json for the data)")
    elif include_scored:
        print(f"unscored · {len(rows)} hireable funnel job(s) incl. already-scored (use --json for the data)")
    else:
        print(f"unscored · {len(rows)} hireable job(s) without a score (use --json for the data)")
    return 0


def cmd_surface(args) -> int:
    from . import surface
    if getattr(args, "json", False):
        import json
        from . import db
        conn = db.connect()
        try:
            data = surface.shortlist_data(conn)
        finally:
            conn.close()
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    surface.main()
    return 0


def cmd_market(args) -> int:
    from . import market
    if getattr(args, "json", False):
        import json
        from . import db
        conn = db.connect()
        try:
            data = market.summary(conn)
        finally:
            conn.close()
        if data is None:  # no jobs yet — stable empty payload (mirrors GET /api/market)
            data = {"total": 0, "relevant": 0, "segments": {}, "top_demand": [],
                    "gaps": [], "salary_pct": 0, "empty": True}
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    market.main()
    return 0


def cmd_stats(args) -> int:
    """Read-only pipeline KPIs (applications funnel) as JSON, for an agent to answer
    "how's my pipeline / what did I apply to this week" without touching SQLite.

    Reuses db.application_funnel (the same computation the tracker page shows). The
    UI hex colors in `funnel` are dropped here so the payload stays clean for Claude.
    """
    import json

    from . import db

    conn = db.connect()
    try:
        data = db.application_funnel(conn)
    finally:
        conn.close()
    # funnel is [(stage, count, color), ...] for the dashboard — strip color for the CLI.
    data["funnel"] = [{"stage": s, "count": c} for (s, c, *_rest) in data.get("funnel", [])]
    print(json.dumps(data, ensure_ascii=False, indent=1))
    return 0


def cmd_daily(args) -> int:
    """The one-shot the scheduler runs: pull (paid unless --read) + score + surface.

    With `--every N` it no-ops unless at least N days have passed since the last
    pull — that's how an "every N days" schedule is enforced while the OS timer
    stays a simple daily trigger.
    """
    import datetime
    import json
    from . import pull, score, surface

    every = int(getattr(args, "every", 0) or 0)
    if every > 1 and not args.read and pull.RUNS_SIDECAR.exists():
        try:
            last = json.loads(pull.RUNS_SIDECAR.read_text()).get("date")
            if last:
                days = (datetime.date.today() - datetime.date.fromisoformat(last)).days
                if days < every:
                    print(f"daily · skipped — last pull {days}d ago (interval is every {every}d)")
                    return 0
        except Exception:
            pass  # any parse issue → just run

    pull.main(["--read"] if args.read else [])
    score.run()
    surface.main()
    # Warm the Discovery cache so the first console load after the daily run is instant
    # (the market payload is seconds to compute; better to pay it here than on the user).
    try:
        from .api.routers import market as market_router
        market_router.warm()
    except Exception as e:
        print(f"daily · warn: could not warm Discovery cache ({e})")
    print("daily · pull + score + surface complete")
    return 0


def cmd_export(args) -> int:
    from . import export
    export.main()
    return 0


def cmd_backfill_events(args) -> int:
    """Seed an initial status_change for apps imported before the v5 event timeline."""
    from . import db
    conn = db.connect()
    n = db.backfill_initial_status_events(conn)
    print(f"backfilled {n} initial status event(s)" if n else "nothing to backfill (timeline already complete)")
    return 0


def cmd_age_applications(args) -> int:
    """Age silent 'Applied' roles (no reply ≥30d) to 'No response'. Idempotent."""
    from . import db
    n = db.age_stale_applications(db.connect())
    print(f"aged {n} application(s) → No response" if n else "nothing to age (no silent applications)")
    return 0


def _web_is_stale(web, out) -> bool:
    """True if any web source file is newer than the built console (e.g. after a git pull)."""
    try:
        index = out / "index.html"
        built_at = index.stat().st_mtime if index.exists() else 0.0
        newest = 0.0
        # Only walk source dirs (never node_modules/out) so this stays fast.
        for sub in ("app", "components", "lib", "public"):
            d = web / sub
            if d.is_dir():
                for f in d.rglob("*"):
                    if f.is_file():
                        newest = max(newest, f.stat().st_mtime)
        for name in ("package.json", "next.config.ts", "tailwind.config.ts", "tsconfig.json", "globals.css"):
            p = web / name
            if p.exists():
                newest = max(newest, p.stat().st_mtime)
        return newest > built_at
    except OSError:
        return False


def _maybe_build_web(no_build: bool) -> None:
    """Build the Next.js console automatically when it's missing OR out of date.

    Keeps `jobcut serve` a one-command experience: the user never runs
    `npm install && npm run build`, and a `git pull` that changes the web source
    is picked up automatically (the built `web/out` is rebuilt when stale).
    Resilient — if Node is missing or the build fails, we serve the API only.
    """
    import shutil
    import subprocess
    from pathlib import Path

    import jobcut

    from .api.app import web_build_dir

    web = Path(jobcut.__file__).resolve().parents[2] / "web"
    if not (web / "package.json").exists():
        return  # installed without the web sources (e.g. a wheel) — nothing to build

    built = web_build_dir()
    stale = bool(built) and _web_is_stale(web, web / "out")
    if built and not stale:
        return  # up to date
    if no_build:
        return
    npm = shutil.which("npm")
    if not npm:
        if not built:
            print("  console: Node/npm not found — serving the API only.")
            print("           install Node 20.9+ from https://nodejs.org, then re-run `jobcut serve`.")
        return  # stale-but-present build is still usable without Node

    print("  console: building the web console" + (" (update detected)…" if stale else " (first run)…"))
    from . import update as _update
    _update.clear_stale_next_lock(web)  # a prior interrupted build must not wedge this one
    try:
        if not (web / "node_modules").exists():
            subprocess.run([npm, "install"], cwd=web, check=True)
        subprocess.run([npm, "run", "build"], cwd=web, check=True)
        print("  console: build complete.")
    except subprocess.CalledProcessError:
        print("  console: web build failed — serving the API only.")
        print("           build it manually with:  cd web && npm install && npm run build")


def _port_in_use(host: str, port: int) -> bool:
    """True if something is already bound to (host, port). SO_REUSEADDR keeps a socket
    lingering in TIME_WAIT from reading as 'in use' — only a live listener counts."""
    import errno
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError as e:
            return e.errno in (errno.EADDRINUSE, errno.EACCES)


def _pids_on_port(port: int) -> list[int]:
    """Best-effort PIDs listening on the TCP port (posix, via lsof). [] if undiscoverable
    (lsof missing, Windows) — callers fall back to printing a manual command."""
    import subprocess

    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


def _probe_health(host: str, port: int, timeout: float = 1.5) -> dict | None:
    """GET /api/health from a server already on the port. Returns the parsed dict, or
    None if nothing answers in time (down, hung mid-build, or too old to have the route)."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001 — unreachable / 404 / bad JSON all mean "not a healthy peer"
        return None


def _server_is_current(host: str, port: int) -> bool:
    """True if the server already on the port is healthy AND running the checked-out code.

    Used by the desktop launcher: a healthy current server is reused (just open the
    browser); anything else — down, hung, or running pre-pull code — is replaced so the
    click always lands on an up-to-date console. A non-git install can't drift, so any
    healthy server there counts as current.
    """
    from . import update as _update

    health = _probe_health(host, port)
    if health is None:
        return False
    checkout = _update.current_sha()
    running = health.get("running_sha")
    if checkout is None or running is None:
        return True  # can't detect drift (non-git, or server predates the sha stamp → reuse)
    return running == checkout


def _open_when_listening(url: str, host: str, port: int, timeout: float = 45.0) -> None:
    """Open the browser once the server actually accepts connections — not on a fixed
    timer. A first-run/after-update build delays the bind by tens of seconds; opening too
    early lands on a dead 'can't connect' tab, which reads as 'the app didn't start'."""
    import threading
    import time
    import webbrowser

    def _wait() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _port_in_use(host, port):  # our uvicorn has bound the socket → ready
                break
            time.sleep(0.3)
        webbrowser.open(url)

    threading.Thread(target=_wait, daemon=True).start()


def _free_port(host: str, port: int) -> bool:
    """Terminate whatever holds the port (SIGTERM, then SIGKILL stragglers) and wait for
    it to free up. Returns True if the port is free afterwards."""
    import os
    import signal
    import time

    pids = _pids_on_port(port)
    if not pids:
        return not _port_in_use(host, port)
    print(f"  --replace: stopping {len(pids)} process(es) on :{port} ({', '.join(map(str, pids))})…")
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        for _ in range(20):  # up to ~2s for the port to clear before escalating
            if not _port_in_use(host, port):
                return True
            time.sleep(0.1)
    return not _port_in_use(host, port)


def cmd_serve(args) -> int:
    """Launch the API (and the static console if built) in one process; --open the browser."""
    try:
        import uvicorn
    except ImportError:
        print("The web console needs the API extra:  pip install 'jobcut[api]'")
        return 1
    import os

    from . import paths, update as _update
    from .api.app import web_build_dir

    url = f"http://{args.host}:{args.port}"
    launcher = getattr(args, "launcher", False)

    # Pre-flight: refuse to start on an occupied port. uvicorn prints its success banner
    # *before* it binds, so a bind clash otherwise reads as a fake "serving…" followed by
    # an error — and the stale process (often a previous `jobcut serve` running OLD code)
    # keeps answering, which is exactly the confusing failure we want to avoid.
    if _port_in_use(args.host, args.port):
        if launcher:
            # Desktop-icon launch: reuse a healthy, up-to-date server; replace anything
            # else. This is what makes "click the icon" reliable — after an update, or if
            # a prior server hung mid-build, the old process is taken over instead of
            # bailing with an (invisible, from a .app) "port in use" error.
            if _server_is_current(args.host, args.port):
                print(f"jobcut is already running at {url} — opening it.")
                if args.open:
                    import webbrowser
                    webbrowser.open(url)
                return 0
            print(f"  replacing the server on :{args.port} (out of date or not responding)…")
            if not _free_port(args.host, args.port):
                print(f"Could not free port {args.port}. Stop it manually:  "
                      f"lsof -ti tcp:{args.port} | xargs kill")
                return 1
        elif getattr(args, "replace", False):
            if not _free_port(args.host, args.port):
                print(f"Could not free port {args.port}. Stop it manually, then retry:")
                print(f"    lsof -ti tcp:{args.port} | xargs kill")
                return 1
        else:
            pids = _pids_on_port(args.port)
            who = f" (PID {', '.join(map(str, pids))})" if pids else ""
            print(f"Port {args.port} is already in use{who} — likely a previous `jobcut serve` "
                  "(maybe running old code).")
            print("Fix it one of these ways:")
            print(f"    jobcut serve --replace            # stop it and take over :{args.port}")
            print(f"    lsof -ti tcp:{args.port} | xargs kill   # free the port yourself")
            print(f"    jobcut serve --port {args.port + 1}            # use a different port")
            return 1

    # Stamp the code revision this process runs so a later `--launcher` start can tell
    # whether the checkout has been pulled ahead of us (→ replace) or not (→ reuse).
    os.environ["JOBCUT_RUNNING_SHA"] = _update.current_sha() or ""

    paths.data_dir().mkdir(parents=True, exist_ok=True)
    _maybe_build_web(getattr(args, "no_build", False))
    # Housekeeping on launch: age silent applications to "No response" so the tracker
    # opens with an honest funnel (and a short, actionable "Needs attention").
    from . import db
    aged = db.age_stale_applications(db.connect())
    if aged:
        print(f"  aged {aged} silent application(s) (no reply ≥{db.NO_RESPONSE_DAYS}d) → No response")
    print(f"jobcut serve · data dir: {paths.data_dir()}")
    if web_build_dir():
        print(f"  console: serving the built web/ console at {url}")
    else:
        print("  console: no build found (web/out). Serving the API only.")
        print("           build it once with:  cd web && npm install && npm run build")
        print("           or run the dev server:  cd web && npm run dev  (then open :3000)")
    print(f"  → {url}   ·   API docs: {url}/docs")

    if args.open:
        # Wait for the socket to actually accept connections (a fresh build can delay the
        # bind by tens of seconds) instead of opening on a fixed timer onto a dead tab.
        _open_when_listening(url, args.host, args.port)

    _start_docs_inbox()

    uvicorn.run("jobcut.api.app:app", host=args.host, port=args.port, log_level="info")
    return 0


def _start_docs_inbox() -> None:
    """Import the documents/ drop-folder once, then watch it for changes (B-22). Any
    markdown file with a `jobcut:` frontmatter block is auto-imported into its application,
    so dropping/editing a file shows up in the console with no CLI call. Best-effort: a
    failure here never blocks `serve`."""
    import threading
    from . import docsinbox, paths

    try:
        docsinbox.ensure_dir()
        s = docsinbox.import_dir()
        bits = []
        if s["written"]:
            bits.append(f"imported {s['written']}")
        if s["offer_level"]:
            bits.append(f"{s['offer_level']} offer-level")
        if s["skipped"]:
            bits.append(f"{s['skipped']} skipped")
        print(f"  documents: watching {paths.documents_dir()}" + (f" · {', '.join(bits)}" if bits else ""))
    except Exception as exc:  # noqa: BLE001 — never let the inbox block serve
        print(f"  documents: inbox import skipped ({exc})")
        return

    def _log(summary: dict) -> None:
        if summary["written"] or summary["skipped"]:
            print(f"  documents: imported {summary['written']}"
                  + (f", {summary['offer_level']} offer-level" if summary["offer_level"] else "")
                  + (f", {summary['skipped']} skipped" if summary["skipped"] else ""))

    threading.Thread(target=docsinbox.watch, kwargs={"on_import": _log}, daemon=True).start()


def _venv_jobcut_bin():
    """The `jobcut` entry point installed next to the running Python. None if absent."""
    from pathlib import Path
    bin = Path(sys.executable).with_name("jobcut")
    if bin.is_file():
        return bin
    if sys.platform == "win32":
        exe = bin.with_suffix(".exe")
        if exe.is_file():
            return exe
    return None


def _assets_dir():
    """Where the shipped brand icons (jobcut.icns / .ico / .png) live."""
    from pathlib import Path
    return Path(__file__).resolve().parent / "assets"


def _serve_cmd_bash(bin: str, data: str, port: int) -> str:
    """Bash launcher body shared by the macOS .app executable and the Linux .desktop.

    `serve --launcher` handles reuse-or-replace itself — open a healthy, up-to-date
    server; take over one that's out of date or hung; start fresh if nothing's there —
    so the launcher is a single exec with no fragile curl guard of its own."""
    return (
        "#!/usr/bin/env bash\n"
        "# jobcut launcher — generated by `jobcut shortcut`. Safe to delete.\n"
        f'export JOBCUT_DATA_DIR="{data}"\n'
        # Apps opened from Finder get a minimal PATH (no Homebrew), so `npm` isn't found and
        # the console is never rebuilt after an update. Add the usual Node locations.
        'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
        f'exec "{bin}" serve --open --launcher --port {port}\n'
    )


_INFO_PLIST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    '<plist version="1.0"><dict>\n'
    "  <key>CFBundleName</key><string>jobcut</string>\n"
    "  <key>CFBundleDisplayName</key><string>jobcut</string>\n"
    "  <key>CFBundleExecutable</key><string>jobcut</string>\n"
    "  <key>CFBundleIconFile</key><string>jobcut</string>\n"
    "  <key>CFBundleIdentifier</key><string>com.jobcut.launcher</string>\n"
    "  <key>CFBundlePackageType</key><string>APPL</string>\n"
    "  <key>CFBundleShortVersionString</key><string>0.1.0</string>\n"
    "  <key>CFBundleVersion</key><string>0.1.0</string>\n"
    "</dict></plist>\n"
)


def _build_macos_app(target, bin: str, data: str, port: int):
    """A minimal jobcut.app bundle — custom icon, and double-clicking it launches the
    console without opening a Terminal window (unlike a bare .command)."""
    import os
    import shutil
    from pathlib import Path

    app = (target / "jobcut.app") if target.is_dir() else Path(target)
    if app.suffix != ".app":
        app = app.with_suffix(".app")
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    exe = macos / "jobcut"
    exe.write_text(_serve_cmd_bash(bin, data, port))
    os.chmod(exe, 0o755)
    icns = _assets_dir() / "jobcut.icns"
    if icns.is_file():
        shutil.copyfile(icns, resources / "jobcut.icns")
    (app / "Contents" / "Info.plist").write_text(_INFO_PLIST)
    (app / "Contents" / "PkgInfo").write_text("APPL????")
    return app


def _build_linux_desktop(target, bin: str, data: str, port: int):
    """A .desktop entry with the brand icon that launches with no terminal."""
    import os
    from pathlib import Path

    icon = _assets_dir() / "jobcut.png"
    inner = (
        f'export JOBCUT_DATA_DIR="{data}"; '
        f'exec "{bin}" serve --open --launcher --port {port}'
    )
    body = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=jobcut\n"
        "Comment=Open the jobcut console\n"
        "Terminal=false\n"
        f"Icon={icon}\n"
        f"Path={data}\n"
        f"Exec=bash -c '{inner}'\n"
    )
    dest = (target / "jobcut.desktop") if target.is_dir() else Path(target).with_suffix(".desktop")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    os.chmod(dest, 0o755)
    return dest


def _build_windows(target, bin: str, data: str, port: int):
    """A jobcut.bat launcher, plus a best-effort .lnk with the brand icon that runs it
    hidden (no console flash) via a .vbs wrapper. Degrades to the .bat if PowerShell or
    the COM shell isn't available."""
    import subprocess
    from pathlib import Path

    base = target if target.is_dir() else Path(target).parent
    base.mkdir(parents=True, exist_ok=True)
    bat = (target / "jobcut.bat") if target.is_dir() else Path(target).with_suffix(".bat")
    bat.write_text(
        "@echo off\r\n"
        "REM jobcut launcher - generated by `jobcut shortcut`. Safe to delete.\r\n"
        f"set JOBCUT_DATA_DIR={data}\r\n"
        f'"{bin}" serve --open --launcher --port {port}\r\n'
    )
    try:
        vbs = base / "jobcut-launch.vbs"
        vbs.write_text(
            'CreateObject("WScript.Shell").Run "cmd /c ""' + str(bat) + '""", 0, False\r\n'
        )
        lnk = base / "jobcut.lnk"
        ico = _assets_dir() / "jobcut.ico"
        ps = (
            "$w=New-Object -ComObject WScript.Shell;"
            f"$s=$w.CreateShortcut('{lnk}');"
            "$s.TargetPath='wscript.exe';"
            f'$s.Arguments=\'"{vbs}"\';'
            f"$s.IconLocation='{ico}';"
            f"$s.WorkingDirectory='{data}';"
            "$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            check=True, capture_output=True, timeout=30,
        )
        return lnk
    except Exception:
        return bat  # PowerShell/COM unavailable — the .bat still works on double-click


def cmd_shortcut(args) -> int:
    """Generate an OS-appropriate desktop launcher with the jobcut icon that opens the
    console on double-click — a real app icon (macOS .app / Linux .desktop / Windows
    .lnk), no terminal window."""
    from pathlib import Path

    from . import paths

    bin = _venv_jobcut_bin()
    if bin is None:
        print(f"Couldn't find the jobcut command next to {sys.executable} — "
              "install jobcut first (pip install -e .)")
        return 1

    data = str(paths.data_dir())

    if args.path:
        target = Path(args.path).expanduser()
    else:
        desktop = Path.home() / "Desktop"
        target = desktop if desktop.is_dir() else paths.data_dir()

    if sys.platform == "darwin":
        dest = _build_macos_app(target, str(bin), data, args.port)
    elif sys.platform == "win32":
        dest = _build_windows(target, str(bin), data, args.port)
    else:
        dest = _build_linux_desktop(target, str(bin), data, args.port)

    print(f"shortcut · created {dest}")
    print("Double-click it to open jobcut (no terminal needed).")
    return 0


def cmd_dashboard(args) -> int:
    import subprocess
    from pathlib import Path
    import jobcut

    # dashboard/app.py lives at the repo root (editable install / clone-and-run).
    app = Path(jobcut.__file__).resolve().parents[2] / "dashboard" / "app.py"
    if not app.exists():
        print("dashboard/app.py not found. From a cloned repo run: streamlit run dashboard/app.py")
        return 1
    try:
        return subprocess.call(["streamlit", "run", str(app)])
    except FileNotFoundError:
        print("Streamlit is not installed. Run: pip install 'jobcut[dashboard]'")
        return 1


def cmd_update(args) -> int:
    """Pull the latest code and rebuild the console (same path as the UI's Update button)."""
    from . import update as _update

    res = _update.run_update(rebuild=not getattr(args, "no_build", False))
    print(res["message"])
    if res.get("blocked"):
        for f in res.get("dirty_files", []):
            print(f"    {f}")
    return 0 if res["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobcut", description="A local, scored LinkedIn job pipeline.")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="set up token, profile, config and searches in the data dir")
    pi.add_argument("--no-input", action="store_true", help="don't prompt for the token (CI/non-interactive)")
    pi.set_defaults(func=cmd_init)

    pp = sub.add_parser("pull", help="pull saved searches from Apify and store them")
    pp.add_argument("--read", action="store_true",
                    help="re-download the last triggered run for free (no new paid scrape)")
    pp.set_defaults(func=cmd_pull)

    psc = sub.add_parser("score", help="filter the funnel and score it against your profile")
    psc.set_defaults(func=cmd_score)

    pis = sub.add_parser("ingest-scores",
                         help="upsert scores from a JSON file (e.g. a Claude/Cowork scoring skill)")
    pis.add_argument("json", help='path to JSON: a list of {job_id, match_score, match_reasons?, '
                                   'status?} or {"scores": [...]}')
    pis.add_argument("--backend", default="claude_skills",
                     help="label the source backend for these scores (default: claude_skills)")
    pis.set_defaults(func=cmd_ingest_scores)

    pip = sub.add_parser("ingest-profile",
                         help="build profile.md + the skills kit from a structured JSON (interview/CV)")
    pip.add_argument("json", help='path to JSON: {target_roles, seniority?, locations, work_types, '
                                  'dealbreakers, skills:[{name,status,category?,aliases?}]}')
    pip.set_defaults(func=cmd_ingest_profile)

    pie = sub.add_parser("ingest-events",
                         help="apply application write-ops from a JSON file (notes, rounds, status, fields)")
    pie.add_argument("json", help='path to JSON: a list of {job_id, status?|fields?|kind+body+meta?, date?} '
                                  'or {"events": [...]}')
    pie.set_defaults(func=cmd_ingest_events)

    pid = sub.add_parser("ingest-documents",
                         help="ingest prep/debrief/study documents from a JSON file (read-only in the console)")
    pid.add_argument("json", help='path to JSON: {"documents": [{job_id, title, body, event_id?, doc_type?, '
                                  'client_key?, supersedes_id?, meta?}], "archive"?: [{doc_id, restore?}]}')
    pid.set_defaults(func=cmd_ingest_documents)

    pim = sub.add_parser("import-docs",
                         help="import prep documents (markdown + jobcut: frontmatter) from the documents/ drop-folder")
    pim.add_argument("--dir", default=None, help="folder to import from (default: <data_dir>/documents)")
    pim.add_argument("--dry-run", action="store_true", help="show the resolution plan without writing")
    pim.set_defaults(func=cmd_import_docs)

    pisal = sub.add_parser("ingest-salary",
                           help="upsert salary estimates from a JSON file (e.g. a Claude/Cowork salary skill)")
    pisal.add_argument("json", help='path to JSON: a list of {job_id, est_min?, est_max?, currency?, '
                                     'period?, basis?} or {"estimates": [...]}')
    pisal.set_defaults(func=cmd_ingest_salary)

    pij = sub.add_parser("import-jobs",
                         help="upsert scraped job rows from a JSON file (no scrape; for a bridge agent)")
    pij.add_argument("json", help='path to JSON: a list of job rows or {"jobs": [...]}; flattened '
                                  "(pull.flatten) or nested harvestapi actor items")
    pij.set_defaults(func=cmd_import_jobs)

    paj = sub.add_parser("add-job", help="add a job manually (by URL or fields); optionally link an application")
    paj.add_argument("--url", default="", help="job posting URL (any ATS); derives a stable job_id")
    paj.add_argument("--company", default="", help="company name")
    paj.add_argument("--title", default="", help="job title")
    paj.add_argument("--location", default="", help="location")
    paj.add_argument("--description", default="", help="job description (optional)")
    paj.add_argument("--job-id", dest="job_id", default="", help="bind to an existing application's job_id (repair an orphan)")
    paj.add_argument("--apply", nargs="?", const="applied", default=None, metavar="STATUS",
                     help="also create/link an application with this status (default: applied)")
    paj.set_defaults(func=cmd_add_job)

    pu = sub.add_parser("unscored", help="list hireable jobs that still need a score (for an external scorer)")
    pu.add_argument("--json", action="store_true", help="print the jobs (with descriptions) as JSON to stdout")
    pu.add_argument("--include-scored", action="store_true",
                    help="also include already-scored funnel jobs (for re-scoring with full descriptions)")
    pu.add_argument("--needs-backend", metavar="BACKEND", default=None,
                    help="funnel jobs NOT yet scored by this backend (e.g. claude_skills) — includes "
                         "rule_based-floored jobs the default would hide; use for Claude/Cowork scoring")
    pu.add_argument("--ids", metavar="ID[,ID...]",
                    help="only these job_ids (with full descriptions), regardless of scored state — targeted re-score")
    pu.set_defaults(func=cmd_unscored)

    psf = sub.add_parser("surface", help="write the ranked shortlist to out/")
    psf.add_argument("--json", action="store_true", help="print the shortlist as JSON to stdout (read-only)")
    psf.set_defaults(func=cmd_surface)

    pdl = sub.add_parser("daily", help="pull + score + surface in one (what the scheduler runs)")
    pdl.add_argument("--read", action="store_true", help="re-download the last run (FREE) instead of a paid scrape")
    pdl.add_argument("--every", type=int, default=0, help="only run if >= N days since the last pull (for 'every N days' schedules)")
    pdl.set_defaults(func=cmd_daily)

    pm = sub.add_parser("market", help="write the market-gaps report and dashboard")
    pm.add_argument("--json", action="store_true", help="print the market summary as JSON to stdout (read-only)")
    pm.set_defaults(func=cmd_market)

    pst = sub.add_parser("stats", help="print pipeline KPIs (applications funnel) as JSON (read-only)")
    pst.add_argument("--json", action="store_true", help="(default) print the funnel as JSON to stdout")
    pst.set_defaults(func=cmd_stats)

    sub.add_parser("export", help="export the DB to CSV/JSON in out/").set_defaults(func=cmd_export)

    sub.add_parser("backfill-events",
                   help="seed an initial status event for apps imported before the timeline (idempotent)"
                   ).set_defaults(func=cmd_backfill_events)

    sub.add_parser("age-applications",
                   help="age silent 'Applied' roles (no reply ≥30d) to 'No response' (idempotent)"
                   ).set_defaults(func=cmd_age_applications)

    ps = sub.add_parser("serve", help="serve the API + web console (one command)")
    ps.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    ps.add_argument("--port", type=int, default=8000, help="bind port (default 8000)")
    ps.add_argument("--open", action="store_true", help="open the console in your browser")
    ps.add_argument("--no-build", action="store_true", help="don't auto-build the web console if it's missing")
    ps.add_argument("--replace", action="store_true",
                    help="if the port is busy, stop the process holding it and take over")
    ps.add_argument("--launcher", action="store_true",
                    help="desktop-icon mode: reuse a healthy up-to-date server, else replace it "
                         "(used by the generated shortcut — makes clicking the icon reliable)")
    ps.set_defaults(func=cmd_serve)

    pu = sub.add_parser("update", help="pull the latest code from the repo and rebuild the console")
    pu.add_argument("--no-build", action="store_true", help="pull only; don't rebuild the web console")
    pu.set_defaults(func=cmd_update)

    psc = sub.add_parser("shortcut", help="create a double-click desktop launcher for the console (no terminal)")
    psc.add_argument("--path", default="", help="where to write the launcher (default: ~/Desktop)")
    psc.add_argument("--port", type=int, default=8000, help="port the launcher opens (default 8000)")
    psc.set_defaults(func=cmd_shortcut)

    sub.add_parser("dashboard", help="launch the Streamlit dashboard").set_defaults(func=cmd_dashboard)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
