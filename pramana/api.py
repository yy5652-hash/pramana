"""HTTP API and static web app.

Routes are thin: each one opens the course database, calls one function from the package and
returns its result as JSON. The browser app in `web/` is served from the same process.
"""
from __future__ import annotations

import json
import re
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import revision, schedule, tutor
from .assess import session
from .cite import citation
from .config import ROOT, settings
from .db import Database, new_id, now, open_course
from .learner import Learner
from .llm import LLMError, ReplayMiss
from .retrieve import index_for
from .stats import course_stats

app = FastAPI(title="Pramana", docs_url="/api/docs", openapi_url="/api/openapi.json")
jobs: dict[str, dict] = {}


def course(course_id: str) -> Database:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", course_id) or not settings.course_db(course_id).exists():
        raise HTTPException(404, f"unknown course '{course_id}'")
    return open_course(course_id)


@app.exception_handler(LLMError)
@app.exception_handler(ReplayMiss)
async def model_unavailable(_, error: Exception) -> JSONResponse:
    return JSONResponse({"detail": f"language model unavailable: {error}"}, status_code=503)


# ---- course ---------------------------------------------------------------------------------

@app.get("/api/courses")
def list_courses() -> list[dict]:
    out = []
    kb_root = settings.data_dir / "kb"
    for path in sorted(kb_root.glob("*/kb.sqlite")) if kb_root.exists() else []:
        course_id = path.parent.name
        manifest = settings.course_dir / course_id / "course.yaml"
        title = course_id
        if manifest.exists():
            import yaml

            title = yaml.safe_load(manifest.read_text()).get("title", course_id)
        out.append({"id": course_id, "title": title})
    return out


@app.get("/api/courses/{course_id}/overview")
def overview(course_id: str) -> dict:
    db = course(course_id)
    sources = db.all("SELECT * FROM sources ORDER BY kind = 'textbook' DESC, kind = 'slides' DESC, id")
    counts: dict[str, dict] = {}
    for row in db.all("SELECT source_id, kind, modality, COUNT(*) AS n FROM units GROUP BY source_id, kind, modality"):
        entry = counts.setdefault(row["source_id"], {"units": 0, "by_kind": {}, "by_modality": {}})
        entry["units"] += row["n"]
        entry["by_kind"][row["kind"]] = entry["by_kind"].get(row["kind"], 0) + row["n"]
        entry["by_modality"][row["modality"]] = entry["by_modality"].get(row["modality"], 0) + row["n"]
    concept_units = {r["concept_id"]: r["n"] for r in db.all("SELECT concept_id, COUNT(*) AS n FROM unit_concepts GROUP BY concept_id")}
    concept_questions = {r["concept_id"]: r["n"] for r in db.all(
        "SELECT concept_id, COUNT(*) AS n FROM questions WHERE status = 'verified' GROUP BY concept_id")}
    return {
        "id": course_id,
        "stats": course_stats(db),
        "sources": [{**s, **counts.get(s["id"], {"units": 0, "by_kind": {}, "by_modality": {}})} for s in sources],
        "topics": db.all("SELECT * FROM topics ORDER BY ord"),
        "concepts": [{**c, "units": concept_units.get(c["id"], 0), "questions": concept_questions.get(c["id"], 0)}
                     for c in db.all("SELECT * FROM concepts ORDER BY ord")],
        "prereqs": db.all("SELECT * FROM prereqs"),
    }


@app.get("/api/courses/{course_id}/units")
def list_units(course_id: str, source_id: str | None = None, concept_id: str | None = None, limit: int = 400) -> list[dict]:
    db = course(course_id)
    index = index_for(course_id, db)
    units = index.units
    if source_id:
        units = [u for u in units if u["source_id"] == source_id]
    if concept_id:
        units = [u for u in units if concept_id in index.unit_concepts.get(u["id"], [])]
    return [{**citation(course_id, u, index.sources[u["source_id"]]), "text": u["text"],
             "concepts": index.unit_concepts.get(u["id"], [])} for u in units[:limit]]


@app.get("/api/courses/{course_id}/units/{unit_id}")
def get_unit(course_id: str, unit_id: str) -> dict:
    db = course(course_id)
    index = index_for(course_id, db)
    unit = index.by_id.get(unit_id)
    if not unit:
        raise HTTPException(404, "unknown unit")
    sibling = index.by_id.get(unit["locator"].get("sibling", ""))
    return {**citation(course_id, unit, index.sources[unit["source_id"]]), "text": unit["text"],
            "sibling_text": sibling["text"] if sibling else None, "concepts": index.unit_concepts.get(unit_id, [])}


@app.get("/api/courses/{course_id}/search")
def search(course_id: str, q: str, k: int = 8) -> list[dict]:
    db = course(course_id)
    index = index_for(course_id, db)
    return [{**citation(course_id, h.unit, index.sources[h.unit["source_id"]], q), "score": round(h.score, 3),
             "dense_rank": h.dense_rank, "lexical_rank": h.lexical_rank} for h in index.search(q, k=k)]


# ---- students -------------------------------------------------------------------------------

class NewStudent(BaseModel):
    name: str


@app.get("/api/courses/{course_id}/students")
def list_students(course_id: str) -> list[dict]:
    return course(course_id).all("SELECT * FROM students WHERE json_extract(profile, '$.simulated') IS NULL ORDER BY created")


@app.post("/api/courses/{course_id}/students")
def create_student(course_id: str, body: NewStudent) -> dict:
    db = course(course_id)
    student = {"id": new_id("s"), "name": body.name.strip()[:60] or "Student", "created": now(), "profile": {}}
    db.insert("students", student)
    return student


@app.get("/api/courses/{course_id}/students/{student_id}")
def student_state(course_id: str, student_id: str) -> dict:
    db = course(course_id)
    student = db.one("SELECT * FROM students WHERE id = ?", [student_id])
    if not student:
        raise HTTPException(404, "unknown student")
    learner = Learner(db, student_id)
    return {
        "student": student,
        "concepts": learner.snapshot(),
        "evidence": db.all("SELECT * FROM evidence WHERE student_id = ? ORDER BY id DESC LIMIT 60", [student_id]),
        "assessments": db.all(
            "SELECT id, kind, created, finished, json_extract(report, '$.score.pct') AS pct FROM assessments "
            "WHERE student_id = ? ORDER BY created DESC LIMIT 20", [student_id]),
        "attempts": db.one("SELECT COUNT(*) AS n, COUNT(DISTINCT question_id) AS distinct_questions FROM attempts WHERE student_id = ?", [student_id]),
    }


class ChatBody(BaseModel):
    message: str
    language: str = "en"
    allow_outside: bool = False


@app.post("/api/courses/{course_id}/students/{student_id}/chat")
def chat(course_id: str, student_id: str, body: ChatBody) -> dict:
    db = course(course_id)
    reply = tutor.respond(db, index_for(course_id, db), course_id, student_id, body.message.strip()[:2000],
                          language=body.language, allow_outside=body.allow_outside)
    return {k: v for k, v in reply.items() if k != "contexts"}


@app.get("/api/courses/{course_id}/students/{student_id}/messages")
def messages(course_id: str, student_id: str) -> list[dict]:
    return course(course_id).all("SELECT * FROM messages WHERE student_id = ? ORDER BY id", [student_id])


@app.get("/api/courses/{course_id}/students/{student_id}/schedule")
def get_schedule(course_id: str, student_id: str, days: int = 14, minutes: int = 45) -> dict:
    return schedule.build(course(course_id), course_id, student_id, days=min(max(days, 2), 60), minutes_per_day=min(max(minutes, 15), 240))


@app.get("/api/courses/{course_id}/students/{student_id}/flashcards")
def get_flashcards(course_id: str, student_id: str) -> list[dict]:
    return revision.flashcards(course(course_id), course_id, student_id)


# ---- assessments ----------------------------------------------------------------------------

class NewAssessment(BaseModel):
    kind: str = "quiz"
    concept_ids: list[str] | None = None
    n: int | None = None
    types: list[str] | None = None


class Answer(BaseModel):
    question_id: str
    response: str | int | float | None = None


@app.post("/api/courses/{course_id}/students/{student_id}/assessments")
def start_assessment(course_id: str, student_id: str, body: NewAssessment) -> dict:
    if body.kind not in session.DEFAULT_LENGTH:
        raise HTTPException(400, "kind must be diagnostic, quiz or exam")
    started = session.start(course(course_id), student_id, body.kind, body.concept_ids,
                            min(body.n, 30) if body.n else None, body.types)
    if started["question"] is None:
        raise HTTPException(409, "no unseen verified questions are left for this scope")
    return started


@app.post("/api/courses/{course_id}/assessments/{assessment_id}/answers")
def submit_answer(course_id: str, assessment_id: str, body: Answer) -> dict:
    return session.answer(course(course_id), course_id, assessment_id, body.question_id, body.response)


@app.get("/api/courses/{course_id}/assessments/{assessment_id}")
def get_assessment(course_id: str, assessment_id: str) -> dict:
    row = course(course_id).one("SELECT * FROM assessments WHERE id = ?", [assessment_id])
    if not row:
        raise HTTPException(404, "unknown assessment")
    return row


# ---- lessons --------------------------------------------------------------------------------

class NewLesson(BaseModel):
    concept_id: str | None = None
    language: str = "en"


@app.get("/api/courses/{course_id}/students/{student_id}/lessons")
def list_lessons(course_id: str, student_id: str) -> dict:
    """This student's lessons, newest first, and the concept the next one should be on."""
    from . import lesson
    from .lesson import voice

    db = course(course_id)
    if not db.one("SELECT id FROM students WHERE id = ?", [student_id]):
        raise HTTPException(404, "unknown student")
    concept_id, why = lesson.next_concept(db, student_id)
    name = db.one("SELECT name FROM concepts WHERE id = ?", [concept_id])["name"]
    rows = db.all("SELECT board FROM lessons WHERE student_id = ? ORDER BY created DESC", [student_id])
    return {"next": {"concept_id": concept_id, "name": name, "why": why}, "lessons": [r["board"] for r in rows], "voice": voice.available()}


@app.post("/api/courses/{course_id}/students/{student_id}/lessons")
def make_lesson(course_id: str, student_id: str, body: NewLesson) -> dict:
    """Start cutting a lesson. It takes a minute or two; poll the job."""
    from . import lesson

    db = course(course_id)
    if not db.one("SELECT id FROM students WHERE id = ?", [student_id]):
        raise HTTPException(404, "unknown student")
    job_id = new_id("job")
    jobs[job_id] = {"id": job_id, "status": "running", "step": "starting", "progress": 0.0}

    def work() -> None:
        try:
            board = lesson.make(db, index_for(course_id, db), course_id, student_id, body.concept_id, body.language,
                                lambda step, done: jobs[job_id].update(step=step, progress=round(done, 3)))
            jobs[job_id].update(status="done", lesson=board, progress=1.0)
        except lesson.NotEnoughMaterial as error:
            jobs[job_id].update(status="failed", error=str(error))
        except (LLMError, ReplayMiss) as error:
            jobs[job_id].update(status="failed", error=f"language model unavailable: {error}")
        except Exception as error:  # surfaced to the UI through the job record
            jobs[job_id].update(status="failed", error=f"{type(error).__name__}: {error}")
            traceback.print_exc()

    threading.Thread(target=work, daemon=True).start()
    return jobs[job_id]


# ---- uploads --------------------------------------------------------------------------------

@app.post("/api/courses/{course_id}/upload")
async def upload(course_id: str, file: UploadFile = File(...)) -> dict:
    """Add a PDF, PPTX or video to a course. Ingestion runs in the background; poll the job."""
    from .ingest import SUFFIX_KIND, concepts as concept_map, ingest_source, store_units

    db = course(course_id)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(file.filename or "upload").name)
    suffix = Path(name).suffix.lower()
    if suffix not in SUFFIX_KIND:
        raise HTTPException(400, "supported files: .pdf, .pptx, .mp4, .mov, .mkv, .webm")
    target = settings.raw_dir / course_id / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        while block := await file.read(1 << 20):
            handle.write(block)
    source = {"id": "up-" + re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")[:40], "kind": SUFFIX_KIND[suffix],
              "title": Path(name).stem.replace("-", " ").replace("_", " "), "file": name, "licence": "uploaded by the student"}
    job_id = new_id("job")
    jobs[job_id] = {"id": job_id, "status": "running", "log": [f"received {name}"], "source_id": source["id"]}

    def work() -> None:
        import numpy as np

        from . import embed

        try:
            units = ingest_source(source, target, settings.asset_dir(course_id), jobs[job_id]["log"].append)
            store_units(db, source, units)
            concepts = db.all("SELECT * FROM concepts ORDER BY ord")
            if concepts and units:
                vectors = np.stack([embed.from_blob(r["vec"]) for r in db.all(
                    "SELECT e.vec FROM embeddings e JOIN units u ON u.id = e.unit_id WHERE u.source_id = ? ORDER BY u.ord", [source["id"]])])
                db.insert_many("unit_concepts", concept_map.tag_units(units, concepts, vectors, jobs[job_id]["log"].append), replace=True)
            index_for(course_id, db).reload()
            jobs[job_id].update(status="done", units=len(units))
        except Exception as error:  # surfaced to the UI through the job record
            jobs[job_id].update(status="failed", error=f"{type(error).__name__}: {error}")
            traceback.print_exc()

    threading.Thread(target=work, daemon=True).start()
    return jobs[job_id]


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    if job_id not in jobs:
        raise HTTPException(404, "unknown job")
    return jobs[job_id]


# ---- evaluation results and files -----------------------------------------------------------

@app.get("/api/courses/{course_id}/evaluation")
def evaluation(course_id: str) -> dict:
    out = {}
    results = ROOT / "evaluation" / "results"
    for path in sorted(results.glob("*.json")) if results.exists() else []:
        out[path.stem] = json.loads(path.read_text())
    return out


@app.get("/media/{course_id}/{name}")
def media(course_id: str, name: str) -> FileResponse:
    path = (settings.raw_dir / course_id / name).resolve()
    if settings.raw_dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)   # Starlette serves byte ranges, so the player can seek


@app.get("/assets/{course_id}/{source_id}/{name}")
def asset(course_id: str, source_id: str, name: str) -> FileResponse:
    root = settings.asset_dir(course_id).resolve()
    path = (root / source_id / name).resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


class WebApp(StaticFiles):
    """The browser app. `no-cache` makes the browser revalidate each file, so an updated
    module is never mixed with stale ones (there is no build step to fingerprint names)."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", WebApp(directory=ROOT / "web", html=True), name="web")
