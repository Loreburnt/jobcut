#!/usr/bin/env python3
"""surface.py — Stage 7: write the ranked shortlist to out/.

Reads jobs + scores from SQLite (db.py), joins them, applies the geo funnel,
collapses reposts, optionally excludes already-applied roles, and writes:
  - out/shortlist.md   (human-readable: today's top + backlog)
  - out/shortlist.csv  (machine-readable)

The "exclude already-applied" feature is OPTIONAL: set $JOBCUT_TRACKER to a
CSV/xlsx with columns Company, Role Title, LinkedIn URL. If unset, it's skipped.
"""

from __future__ import annotations

import datetime
import json
import os
import re

import pandas as pd

from . import config, db, paths, salaryparse
from .route import funnel_series

TOP_N = 10          # CLI markdown digest: a tight "top N" highlight list
FEED_LIMIT = 300    # web feed per list: a safety ceiling only — the min-match slider is
                    # the real filter, so the feed returns ~everything above the floor
                    # (the frontend reveals them progressively with "Show more").

# match_score bands for the Discovery histogram, aligned to the shortlist thresholds
# (min_score=60 = shortlist floor, backlog_min=75 = "top"). [lo, hi) except the last.
SCORE_BANDS = [(0, 60, "Below bar"), (60, 75, "Shortlist"), (75, 101, "Top")]


def score_distribution(conn) -> dict:
    """How your scored offers spread across match-score bands (a pipeline-quality view).

    Deduped by canonical_id (reposts collapsed, best score kept) so a role posted five
    times counts once. Out-of-profile titles are already pre-discarded before scoring, so
    this is the shape of your *in-profile* pipeline. Empty-safe: zeroed bands, no jobs.
    """
    s = db.read_scores(conn)
    zero = {"total": 0, "median": 0,
            "bands": [{"label": lbl, "min": lo, "max": hi, "count": 0} for lo, hi, lbl in SCORE_BANDS]}
    if s.empty:
        return zero
    s = s.copy()
    s["score"] = pd.to_numeric(s.match_score, errors="coerce")
    s = s.dropna(subset=["score"])
    if s.empty:
        return zero
    # collapse reposts: prefer canonical_id, fall back to job_id; keep the best score
    cid = s.get("canonical_id")
    s["key"] = (cid.astype(str).str.strip() if cid is not None else "").replace("", pd.NA)
    s["key"] = s["key"].fillna(s["job_id"])
    s = s.sort_values("score", ascending=False).drop_duplicates("key")

    bands = [{"label": lbl, "min": lo, "max": hi,
              "count": int(((s.score >= lo) & (s.score < hi)).sum())}
             for lo, hi, lbl in SCORE_BANDS]
    return {"total": int(len(s)), "median": int(s.score.median()), "bands": bands}


def shortlist_skill_gaps(conn, *, min_score: int = 60, limit: int = 8) -> dict:
    """Gap skills the offers you'd actually apply to (score ≥ min_score) ask for most.

    Unlike the market-wide gaps (over every relevant offer), this is scoped to YOUR
    shortlist — the skills holding back the roles you're a real match for. Regex-derived
    per offer, deduped by canonical_id. Empty-safe.
    """
    from . import config, market
    tax = config.load_taxonomy(required=False)
    empty = {"n": 0, "gaps": []}
    if not tax or not tax.get("skills"):
        return empty
    s = db.read_scores(conn)
    if s.empty:
        return empty
    s = s.copy()
    s["score"] = pd.to_numeric(s.match_score, errors="coerce")
    s = s[s.score >= min_score]
    if s.empty:
        return empty
    jobs = db.read_jobs(conn, columns=["job_id", "title", "description"])
    if jobs.empty:
        return empty
    df = jobs.merge(s[["job_id", "score", "canonical_id"]], on="job_id", how="inner")
    if df.empty:
        return empty
    df["key"] = df.canonical_id.astype(str).str.strip().replace("", pd.NA).fillna(df.job_id)
    df = df.sort_values("score", ascending=False).drop_duplicates("key")

    # Same "missing gap" definition as skill_matcher (status == "gap"), minus close_via=="skip"
    # for consistency with the market-wide gaps — but vectorized: one regex pass per gap skill
    # over the shortlist text instead of a Python loop over every offer × every skill.
    text = (df.title.astype(str) + " " + df.description.astype(str))
    gap_skills = {k: v for k, v in tax["skills"].items()
                  if v.get("status") == "gap" and v.get("close_via") != "skip"}
    counts = {k: c for k, m in market._skill_hitmasks(text, gap_skills).items()
              if (c := int(m.sum())) > 0}
    n = int(len(df))
    skills = tax["skills"]
    gaps = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    out = [{"skill": k, "n": v, "pct": round(100 * v / n) if n else 0,
            "close_via": skills.get(k, {}).get("close_via", ""), "cat": skills.get(k, {}).get("cat", "")}
           for k, v in gaps]
    return {"n": n, "gaps": out}


def norm(x):
    return re.sub(r"\s+", " ", str(x).strip().lower())


def blank(v):
    return v in (None, "") or (isinstance(v, float) and pd.isna(v)) or str(v).strip().lower() in ("", "nan", "none", "nat")


def offer_link(r):
    for c in (r.linkedin_url, r.apply_url, r.easy_apply_url):
        if not blank(c):
            return str(c)
    return ""


def nextstep(r):
    if not blank(r.apply_url):
        return f"apply via [ATS]({r.apply_url})"
    if not blank(r.recruiter_name):
        return (f"contact recruiter [{r.recruiter_name}]({r.recruiter_url})"
                if not blank(r.recruiter_url) else f"contact recruiter {r.recruiter_name}")
    if not blank(r.easy_apply_url):
        return "Easy Apply on LinkedIn"
    if blank(r.linkedin_url):
        return "search on LinkedIn (no direct link)"
    return "review and apply on LinkedIn"


def line(i, r):
    fire = "🔥 " if (r.score or 0) >= 80 else ""
    return (f"{i}. {fire}**{str(r.title)[:70]} — {r.company_name}** ({int(r.score)}) · "
            f"[offer]({offer_link(r)}) — {str(r.match_reasons or '').strip()} — → {nextstep(r)}")


def load_applied():
    """Optional already-applied exclusion via $JOBCUT_TRACKER (CSV or xlsx)."""
    applied_ids, applied_ct = set(), set()
    tp = os.environ.get("JOBCUT_TRACKER")
    if not tp:
        return applied_ids, applied_ct
    from pathlib import Path
    p = Path(tp).expanduser()
    if not p.exists():
        print(f"  note: JOBCUT_TRACKER set but {p} not found — skipping applied-exclusion")
        return applied_ids, applied_ct
    ap = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    for _, r in ap.iterrows():
        u = str(r.get("LinkedIn URL", ""))
        mt = re.search(r"/jobs/view/(\d+)", u)
        if mt:
            applied_ids.add(mt.group(1))
        applied_ct.add((norm(r.get("Company", "")), norm(r.get("Role Title", ""))))
    return applied_ids, applied_ct


# columns surfaced to JSON/CSV consumers (the API and shortlist.csv)
# `first_seen` = when we first pulled the offer; `posted_date` = the offer's own
# publish date (from Apify) — both drive the freshness line on each card.
RECORD_FIELDS = ["job_id", "title", "company_name", "location", "score", "match_reasons",
                 "linkedin_url", "apply_url", "easy_apply_url", "scored_date",
                 "workplace_type", "status", "backend", "first_seen", "posted_date",
                 "auto_score", "auto_reasons", "claude_score", "claude_reasons"]
_INT_FIELDS = {"score", "auto_score", "claude_score"}

# jobs columns the shortlist actually needs (drops `description` + other heavy text);
# the rest of a shortlist row comes from the scores table. Used by the API path only —
# the CLI .md export (main) reads full rows for recruiter/salary fields.
SHORTLIST_JOB_COLS = ["job_id", "title", "company_name", "location", "workplace_type",
                      "linkedin_url", "apply_url", "easy_apply_url", "expire_at",
                      "first_seen", "posted_date"]


def _ranked_funnel(conn, applied_ids, applied_ct, today, light=False):
    """Shared selection: funnel ∩ scored, reposts collapsed, applied/expired removed.

    Returns (m, df, f, n_excluded). `f` is the cleaned, ranked frame; `m`/`df` feed counts.
    `f` is None when there are no jobs. `light=True` reads only the columns the API
    shortlist needs (skips `description`); the CLI export keeps the full read.
    """
    m = db.read_jobs(conn, columns=SHORTLIST_JOB_COLS if light else None)
    s = db.read_scores(conn)
    if m.empty:
        return m, None, None, 0

    df = m.merge(s, on="job_id", how="left")
    df["geo_ok"] = funnel_series(df.location, df.workplace_type)   # vectorized (no per-row apply)
    # A job Claude has reviewed is in the funnel even if its listed location is outside
    # your geography: Claude read the posting (e.g. "fully remote in Europe" listed under
    # Estonia) and judged eligibility itself. The auto view still uses the geo gate.
    _backend = df["backend"] if "backend" in df.columns else pd.Series("", index=df.index)
    df["funnel"] = df["geo_ok"] | _backend.fillna("").eq("claude_skills")
    f = df[df.funnel].copy()
    f["score"] = pd.to_numeric(f.match_score, errors="coerce")

    if "canonical_id" not in f.columns:
        f["canonical_id"] = ""
    f["canonical_id"] = f.canonical_id.fillna("").replace("", pd.NA)
    f["canonical_id"] = f.canonical_id.fillna(f.company_name.map(norm) + "|" + f.title.map(norm) + "|" + f.location.map(norm))

    f["_ct"] = list(zip(f.company_name.map(norm), f.title.map(norm)))
    before = len(f)
    f = f[~(f.job_id.isin(applied_ids) | f._ct.isin(applied_ct))].copy()
    n_excl = before - len(f)

    f["has_link"] = (~f.linkedin_url.map(blank).astype(bool)) | (~f.apply_url.map(blank).astype(bool)) | (~f.easy_apply_url.map(blank).astype(bool))
    f["_exp"] = pd.to_datetime(f.expire_at, errors="coerce")
    f["expired"] = f._exp.notna() & (f._exp.dt.strftime("%Y-%m-%d") < today)
    f["has_url"] = (~f.linkedin_url.map(blank).astype(bool)).astype(int)

    # collapse reposts, keep best score / with link
    f = f.sort_values(["score", "has_url"], ascending=False).drop_duplicates("canonical_id", keep="first").drop_duplicates("_ct", keep="first")
    f = f[f.has_link & ~f.expired].copy()
    return m, df, f, n_excl


def last_pull_date() -> str | None:
    """Date of the last Apify pull (``last_runs.json``) — i.e. when 'Find new jobs'
    last ran. ``None`` if nothing has been pulled yet. Lets the console tell the user
    how fresh the whole shortlist is, not just each card."""
    p = paths.data_dir() / "last_runs.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text()).get("date")
        return str(d) if d else None
    except Exception:
        return None


def _records(frame):
    """A ranked frame -> JSON-safe list of dicts (numpy/NaN scrubbed)."""
    cols = [c for c in RECORD_FIELDS if c in frame.columns]
    rows = []
    for _, r in frame[cols].iterrows():
        d = {}
        for c in cols:
            if c in _INT_FIELDS:
                v = pd.to_numeric(r[c], errors="coerce")
                d[c] = int(v) if pd.notna(v) else None
            else:
                d[c] = None if blank(r[c]) else str(r[c])
        rows.append(d)
    return rows


# --- Card extras: salary + country on every shortlist card (added for Arantza) ----------
_REGION_LABELS = {"european union": "European Union", "emea": "EMEA", "europe": "Europe",
                  "european economic area": "European Economic Area", "worldwide": "Worldwide"}


def country_from_location(loc) -> str | None:
    """Best-effort country (or region) from a LinkedIn location string.

    "Barcelona, Catalonia, Spain" -> "Spain"; "EMEA" -> "EMEA"; "Remote"/blank -> None.
    """
    if blank(loc):
        return None
    last = str(loc).split(",")[-1].strip()
    if not last or last.lower() in ("remote", "remoto", "anywhere"):
        return None
    if last.lower().startswith("greater "):        # "Greater Dublin" -> keep as given
        return last
    return _REGION_LABELS.get(last.lower(), last)


def _fmt_money(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n/1000:.0f}k" if n >= 1000 else f"{n:.0f}"


def _card_extras(conn, rows: list[dict]) -> None:
    """Add `country`, `salary` and `salary_kind` (listed | estimate | None) to card dicts."""
    if not rows:
        return
    ids = [r["job_id"] for r in rows]
    qs = ",".join("?" * len(ids))
    jobs = {str(r[0]): r for r in conn.execute(
        f"SELECT job_id, salary_text, salary_min, salary_max, description FROM jobs WHERE job_id IN ({qs})", ids)}
    try:
        ests = {str(r[0]): r for r in conn.execute(
            f"SELECT job_id, est_min, est_max, currency FROM salary_estimates WHERE job_id IN ({qs})", ids)}
    except Exception:
        ests = {}
    for d in rows:
        d["country"] = country_from_location(d.get("location"))
        d["salary"], d["salary_kind"] = None, None
        j = jobs.get(str(d["job_id"]))
        if j is not None:
            _, st, mn, mx, desc = j
            if not blank(st):
                d["salary"], d["salary_kind"] = str(st), "listed"
            elif not blank(mn) or not blank(mx):
                d["salary"] = " - ".join(_fmt_money(x) for x in (mn, mx) if not blank(x))
                d["salary_kind"] = "listed"
            else:
                phrase = salaryparse.salary_text_from_description(desc)
                if phrase:
                    d["salary"], d["salary_kind"] = phrase, "listed"
        if d["salary"] is None and str(d["job_id"]) in ests:
            _, emn, emx, cur = ests[str(d["job_id"])]
            if not blank(emn) or not blank(emx):
                band = " - ".join(_fmt_money(x) for x in (emn, emx) if not blank(x))
                d["salary"] = f"~{band} {cur or ''}".strip()
                d["salary_kind"] = "estimate"


def _auto_scores(conn, job_ids) -> dict:
    """Rule-based ("automatic") score for each job, computed live so it is always
    available next to Claude's review, even after Claude's scores were ingested."""
    ids = [str(j) for j in job_ids]
    if not ids:
        return {}
    from .score import _rule_based_kwargs
    from .scoring import get_scorer
    scorer = get_scorer("rule_based", **_rule_based_kwargs(config.load()))
    qs = ",".join("?" * len(ids))
    cur = conn.execute(f"SELECT * FROM jobs WHERE job_id IN ({qs})", ids)
    cols = [c[0] for c in cur.description]
    out = {}
    for row in cur.fetchall():
        job = dict(zip(cols, row))
        try:
            js = scorer.score(job, "")
            out[str(job["job_id"])] = (js.match_score, js.match_reasons)
        except Exception:
            out[str(job["job_id"])] = (None, None)
    return out


def shortlist_data(conn, *, min_score=60, backlog_min=75, q=None, location=None,
                   recency_days=None, include_applied=False, today=None,
                   limit=FEED_LIMIT, basis="claude") -> dict:
    """The ranked shortlist as data (the GET /api/shortlist payload).

    Excludes already-applied roles by `applications.job_id` (not the CSV tracker)
    unless `include_applied`. Returns {today, backlog, meta}. `limit` caps each list
    high enough that lowering `min_score` visibly adds cards (the CLI digest uses the
    tighter TOP_N instead).
    """
    today = today or datetime.date.today().isoformat()
    if include_applied:
        applied_ids = set()
    else:
        apps = db.read_applications(conn)
        applied_ids = set(apps.job_id) if not apps.empty else set()

    m, df, f, n_excl = _ranked_funnel(conn, applied_ids, set(), today, light=True)
    meta = {"db_count": int(len(m)), "funnel_count": 0, "excluded": int(n_excl),
            "last_pull": last_pull_date(), "last_scored": None}
    if f is None or f.empty:
        return {"today": [], "backlog": [], "meta": meta}
    meta["funnel_count"] = int(df.funnel.sum())

    # Two views of the same jobs: Claude's review vs the automatic (rule-based) score.
    is_claude = f["backend"].fillna("").eq("claude_skills") if "backend" in f.columns else pd.Series(False, index=f.index)
    auto = _auto_scores(conn, f.job_id)
    f["auto_score"] = f.job_id.astype(str).map(lambda j: auto.get(j, (None, None))[0])
    f["auto_reasons"] = f.job_id.astype(str).map(lambda j: auto.get(j, (None, None))[1])
    f["claude_score"] = f.score.where(is_claude)
    f["claude_reasons"] = f.match_reasons.where(is_claude)
    meta["claude_count"] = int(is_claude.sum())
    meta["basis"] = basis
    if basis == "auto":
        f = f[f.geo_ok].copy()
        f["score"] = pd.to_numeric(f.auto_score, errors="coerce")
        f["match_reasons"] = f.auto_reasons
        f["backend"] = "rule_based"
        f["scored_date"] = f.first_seen        # "latest" = newest pull, not scoring batch
    else:
        f = f[is_claude.reindex(f.index, fill_value=False)].copy()

    if q:
        ql = q.lower()
        f = f[f.title.str.lower().str.contains(ql, na=False) | f.company_name.str.lower().str.contains(ql, na=False)]
    if location:
        f = f[f.location.str.lower().str.contains(location.lower(), na=False)]
    if recency_days is not None:
        cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=recency_days)).isoformat()
        f = f[f.scored_date.astype(str) >= cutoff]

    sd = f.scored_date.astype(str)
    # "Latest batch" = the most recent scoring date present, NOT the literal calendar
    # day. Scoring is batched (the user doesn't score every day), so a strict `== today`
    # left the top list perpetually empty. The user-facing `min_score` is the floor for
    # BOTH lists — the control filters the whole feed, not just the fresh batch.
    # (`backlog_min` kept in the signature for API back-compat; superseded by min_score.)
    latest = sd.max() if len(sd) else today
    meta["last_scored"] = str(latest) if (len(sd) and str(latest)[:4].isdigit()) else None
    today_top = f[(sd == latest) & (f.score >= min_score)].sort_values("score", ascending=False).head(limit)
    backlog = f[(sd < latest) & (f.score >= min_score)].sort_values("score", ascending=False).head(limit)
    today_rows, backlog_rows = _records(today_top), _records(backlog)
    _card_extras(conn, today_rows)
    _card_extras(conn, backlog_rows)
    return {"today": today_rows, "backlog": backlog_rows, "meta": meta}


def main(conn=None):
    own = conn is None
    conn = conn or db.connect()
    today = datetime.date.today().isoformat()

    applied_ids, applied_ct = load_applied()
    m, df, f, n_excl = _ranked_funnel(conn, applied_ids, applied_ct, today)
    if own:
        conn.close()

    md_path = paths.out_dir() / "shortlist.md"
    if m.empty:
        md_path.write_text(f"# 🎯 Shortlist\n\n*Generated {today} — no jobs yet. Run `jobcut pull` first.*\n")
        print(f"wrote {md_path}: empty (no jobs in the database)")
        return

    scored = f[f.status == "scored"]
    sd = f.scored_date.astype(str)
    n_today = int((sd == today).sum())
    today_top = f[(sd == today) & (f.score >= 60)].sort_values("score", ascending=False).head(TOP_N)
    backlog = f[(sd < today) & (f.score >= 75)].sort_values("score", ascending=False).head(TOP_N)

    out = [
        "# 🎯 Shortlist\n",
        f"*Generated {today} · DB {len(m)} · funnel {int(df.funnel.sum())} · "
        f"{len(scored)} scored unapplied · {n_excl} excluded (already in tracker) · "
        f"reposts collapsed, valid link only.*\n",
        f"**Summary:** {n_today} scored in today's batch · top {TOP_N} ≥60 below · "
        f"{int((scored.score >= 60).sum())} in backlog ≥60.\n",
        f"## New in today's batch — top {TOP_N} (score ≥60)\n",
    ]
    out += [line(i, r) for i, (_, r) in enumerate(today_top.iterrows(), 1)] or ["_None ≥60 in today's batch._"]
    out += ["", f"## 🗂️ Backlog highlights — top {TOP_N} (≥75, prior days, unapplied)\n"]
    out += [line(i, r) for i, (_, r) in enumerate(backlog.iterrows(), 1)] or ["_None ≥75 in the backlog._"]
    out += ["\n> Set $JOBCUT_TRACKER to a CSV/xlsx to exclude already-applied roles."]
    md_path.write_text("\n".join(out))

    surfaced = pd.concat([today_top, backlog]).drop_duplicates("job_id")
    csv_cols = ["job_id", "title", "company_name", "location", "score", "match_reasons",
                "linkedin_url", "apply_url", "scored_date"]
    surfaced[[c for c in csv_cols if c in surfaced.columns]].to_csv(paths.out_dir() / "shortlist.csv", index=False)

    print(f"wrote {md_path}: {len(today_top)} today-batch (top {TOP_N}), {len(backlog)} backlog, {n_excl} already-applied excluded")


if __name__ == "__main__":
    main()
