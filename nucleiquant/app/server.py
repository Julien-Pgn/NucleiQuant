"""NucleiQuant web app: a thin HTTP layer over nucleiquant.api."""

import os
import threading

import markdown
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..api import ApiError, Session
from ..contours import pack_outlines
from ..jobs import JobManager

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DOCS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs"))


def create_app():
    app = FastAPI(title="NucleiQuant", docs_url=None, redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=4)
    session = Session(JobManager())
    app.state.session = session
    threading.Thread(target=session.detect_device, daemon=True).start()

    @app.exception_handler(ApiError)
    def api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    def key_error(_: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'\"")})

    def binary(data, shape, dtype):
        return Response(content=data, media_type="application/octet-stream",
                        headers={"X-Shape": ",".join(map(str, shape)), "X-Dtype": dtype, "Cache-Control": "no-store"})

    # ---- app shell ---------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/state")
    def state():
        return session.state()

    @app.get("/api/system")
    def system():
        return session.system()

    @app.get("/api/browse")
    def browse(path: str = ""):
        return session.browse(path or None)

    @app.get("/api/recent")
    def recent():
        return session.recent()

    @app.get("/api/suggest-name")
    def suggest_name(images_dir: str):
        return {"name": session.suggest_name(images_dir)}

    @app.get("/api/help", response_class=HTMLResponse)
    def help_page():
        path = os.path.join(DOCS, "user_guide.md")
        if not os.path.exists(path):
            return "<p>The user guide is missing from this installation.</p>"
        with open(path, encoding="utf-8") as f:
            return markdown.markdown(f.read(), extensions=["tables", "fenced_code", "toc"])

    @app.get("/api/help/{name}")
    def help_asset(name: str):
        path = os.path.join(DOCS, "images", os.path.basename(name))
        if not os.path.exists(path):
            raise HTTPException(404)
        return FileResponse(path)

    @app.post("/api/quit")
    def quit_app():
        threading.Timer(0.4, lambda: os._exit(0)).start()
        return {"ok": True}

    # ---- project -----------------------------------------------------------------
    @app.post("/api/projects")
    def create_project(images_dir: str = Body(...), name: str = Body(...)):
        return session.create_project(images_dir, name)

    @app.post("/api/projects/open")
    def open_project(path: str = Body(..., embed=True)):
        return session.open_project(path)

    @app.post("/api/projects/close")
    def close_project():
        return session.close_project()

    @app.patch("/api/project")
    def update_project(changes: dict = Body(...)):
        return session.update_project(changes)

    @app.get("/api/files")
    def files():
        return session.files()

    # ---- survey ------------------------------------------------------------------
    @app.post("/api/survey")
    def start_survey():
        return session.start_survey()

    @app.get("/api/survey")
    def survey_data():
        return session.survey_data()

    @app.post("/api/survey/channel")
    def survey_channel(channel: int = Body(..., embed=True)):
        return session.set_survey_channel(channel)

    @app.post("/api/survey/selection")
    def survey_selection(selection: list = Body(..., embed=True)):
        return session.set_selection(selection)

    @app.post("/api/survey/reset")
    def survey_reset():
        return session.reset_selection()

    # ---- crops -------------------------------------------------------------------
    @app.post("/api/crops")
    def start_crops():
        return session.start_crops()

    @app.post("/api/crops/{crop_id}/move")
    def move_crop(crop_id: str, y: int = Body(...), x: int = Body(...)):
        return session.move_crop(crop_id, y, x)

    @app.get("/api/crops/{crop_id}/thumb")
    def crop_thumb(crop_id: str):
        return FileResponse(session.crop_file(crop_id, "thumb"), headers={"Cache-Control": "no-store"})

    @app.get("/api/crops/{crop_id}/film")
    def crop_film(crop_id: str):
        return FileResponse(session.crop_file(crop_id, "film"), headers={"Cache-Control": "no-store"})

    @app.get("/api/crops/{crop_id}/raw")
    def crop_raw(crop_id: str):
        data, shape = session.crop_raw(crop_id)
        return binary(data, shape, "uint16")

    @app.get("/api/crops/{crop_id}/labels")
    def crop_labels(crop_id: str):
        data, shape = session.crop_labels(crop_id)
        return binary(data, shape, "uint32")

    @app.get("/api/crops/{crop_id}/outlines")
    def crop_outlines(crop_id: str):
        return binary(session.crop_outlines(crop_id), [1], "outlines")

    @app.get("/api/crops/{crop_id}/objects")
    def crop_objects(crop_id: str):
        return session.crop_objects(crop_id)

    @app.get("/api/crops/{crop_id}/annotations")
    def crop_annotations(crop_id: str):
        return session.labels_of_crop(crop_id)

    @app.get("/api/crops/{crop_id}/predictions")
    def crop_predictions(crop_id: str):
        return session.crop_predictions(crop_id)

    # ---- categories and labels -------------------------------------------------------
    @app.post("/api/categories")
    def add_category(name: str = Body(...), color: str = Body(None)):
        return session.add_category(name, color)

    @app.patch("/api/categories/{category_id}")
    def update_category(category_id: str, name: str = Body(None), color: str = Body(None)):
        return session.update_category(category_id, name, color)

    @app.delete("/api/categories/{category_id}")
    def delete_category(category_id: str):
        return session.delete_category(category_id)

    @app.post("/api/labels")
    def set_label(crop_id: str = Body(...), label: int = Body(...), category_id: str = Body(None)):
        return session.set_label(crop_id, label, category_id)

    # ---- classifier --------------------------------------------------------------------
    @app.post("/api/train")
    def train():
        return session.start_training()

    @app.get("/api/classifier")
    def classifier():
        return session.classifier_info()

    @app.post("/api/classifier/validate")
    def validate():
        return session.validate_classifier()

    @app.post("/api/classifier/import")
    def import_classifier(path: str = Body(..., embed=True)):
        return session.import_classifier(path)

    # ---- batch and results -------------------------------------------------------------
    @app.post("/api/batch")
    def start_batch():
        return session.start_batch()

    @app.get("/api/results")
    def results():
        return session.results()

    @app.post("/api/results/refresh")
    def refresh_results():
        return session.refresh_results()

    @app.get("/api/results/excel")
    def excel():
        path = session.excel_path()
        return FileResponse(path, filename=os.path.basename(path),
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    view_cache = {}

    def view(image):
        if view_cache.get("image") != image:
            view_cache.clear()
            view_cache.update(session.image_view(image), image=image)
        return view_cache

    @app.get("/api/images/{image}/raw")
    def image_raw(image: str):
        v = view(image)
        return binary(v["raw"].tobytes(), v["raw"].shape, "uint16")

    @app.get("/api/images/{image}/labels")
    def image_labels(image: str):
        v = view(image)
        return binary(v["labels"].tobytes(), v["labels"].shape, "uint32")

    @app.get("/api/images/{image}/outlines")
    def image_outlines(image: str):
        import numpy as np
        v = view(image)
        z = np.load(v["paths"]["outlines"])
        f = v["scale"]
        return binary(pack_outlines(z["ids"], z["offsets"], z["ys"] // f, z["xs"] // f), [f], "outlines")

    @app.get("/api/images/{image}/predictions")
    def image_predictions(image: str):
        import numpy as np
        v = view(image)
        z = np.load(v["paths"]["pred"])
        return {"labels": z["labels"].tolist(), "category": z["category"].tolist(),
                "probability": np.round(z["probability"], 3).tolist()}

    # ---- jobs --------------------------------------------------------------------------
    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        j = session.jobs.get(job_id)
        if j is None:
            raise HTTPException(404, "No such job")
        return j

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return session.jobs.cancel(job_id)

    return app
