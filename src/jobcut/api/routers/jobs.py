"""Shortlist + job detail (the 'Hoy' and 'Detalle' sections)."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ... import config, db, market, salaryparse, surface
from ..deps import get_conn

router = APIRouter(tags=["jobs"])


@router.get("/shortlist")
def get_shortlist(
    min_score: int = 60,
    backlog_min: int = 75,
    q: str | None = None,
    location: str | None = None,
    recency_days: int | None = None,
    include_applied: bool = False,
    basis: str = "claude",
    conn: sqlite3.Connection = Depends(get_conn),
):
    return surface.shortlist_data(
        conn, min_score=min_score, backlog_min=backlog_min, q=q, location=location,
        recency_days=recency_days, include_applied=include_applied,
        basis="auto" if basis == "auto" else "claude",
    )


def _scrub_row(row) -> dict:
    return {k: (None if surface.blank(v) else str(v)) for k, v in dict(row).items()}


def _parse_skill_cell(srow, col: str) -> list | None:
    """Parse a scores.skills_* JSON cell into a list. None when empty/absent/malformed."""
    if srow is None:
        return None
    raw = dict(srow).get(col)
    if surface.blank(raw):
        return None
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return v if isinstance(v, list) and v else None


@router.get("/jobs/{job_id}")
def get_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    # Targeted lookups by primary key — O(1). (Reading the whole jobs+scores tables
    # into pandas to find one row cost ~340ms on a 2k-row DB.)
    row = db.get_job_row(conn, job_id)
    srow = db.get_score_row(conn, job_id)
    application = db.get_application(conn, job_id)
    estrow = db.get_salary_estimate_row(conn, job_id)

    # Never 404 a row the user owns: an imported application (or a score) with no
    # jobs row still opens with job:null so notes + status stay reachable (KR-v2-5).
    if row is None and srow is None and application is None:
        raise HTTPException(status_code=404, detail="job not found")

    job = _scrub_row(row) if row is not None else None

    score = None
    if srow is not None:
        s = dict(srow)
        ms = s.get("match_score")
        score = {
            "match_score": int(ms) if str(ms).strip() not in ("", "nan", "None") else None,
            "match_reasons": None if surface.blank(s.get("match_reasons")) else str(s["match_reasons"]),
            "status": None if surface.blank(s.get("status")) else str(s["status"]),
            "scored_date": None if surface.blank(s.get("scored_date")) else str(s["scored_date"]),
            "backend": None if surface.blank(s.get("backend")) else str(s["backend"]),
        }

    # B-17: when the employer disclosed a salary but only in the description body (not the
    # structured fields), surface that phrase — distinct from a Cowork estimate.
    salary_listing = None
    if job is not None:
        has_struct = any(not surface.blank(job.get(k)) for k in ("salary_text", "salary_min", "salary_max"))
        if not has_struct:
            salary_listing = salaryparse.salary_text_from_description(job.get("description"))

    salary_estimate = None
    if estrow is not None:
        e = dict(estrow)
        def _int(v):
            return int(v) if str(v).strip() not in ("", "None", "nan") else None
        salary_estimate = {
            "est_min": _int(e.get("est_min")),
            "est_max": _int(e.get("est_max")),
            "currency": None if surface.blank(e.get("currency")) else str(e["currency"]),
            "period": None if surface.blank(e.get("period")) else str(e["period"]),
            "basis": None if surface.blank(e.get("basis")) else str(e["basis"]),
            "source": None if surface.blank(e.get("source")) else str(e["source"]),
            "estimated_at": None if surface.blank(e.get("estimated_at")) else str(e["estimated_at"]),
        }

    # Per-offer skills the user has vs lacks. Prefer Claude's persisted semantic judgment
    # (skills_matched/missing on the score row, source="claude"); else derive on the fly
    # from taxonomy + offer text (source="taxonomy") — the no-LLM floor, always available.
    skills_match = None
    cl_matched = _parse_skill_cell(srow, "skills_matched")
    cl_missing = _parse_skill_cell(srow, "skills_missing")
    if cl_matched or cl_missing:
        skills_match = {"matched": cl_matched or [], "missing": cl_missing or [], "source": "claude"}
    elif job is not None:
        tax = config.load_taxonomy(required=False)
        if tax and tax.get("skills"):
            text = f"{job.get('title', '')} {job.get('description', '')}"
            skills_match = {**market.skill_matcher(tax)(text), "source": "taxonomy"}

    return {"job": job, "score": score, "application": application,
            "salary_listing": salary_listing, "salary_estimate": salary_estimate,
            "skills_match": skills_match}
