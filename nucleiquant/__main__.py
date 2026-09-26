"""Command line: `python -m nucleiquant serve` (the app) or `batch` (headless run)."""

import argparse
import os
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nucleiquant", description="Count cell types in fluorescence images.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the app (open http://localhost:8765 in a browser).")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    run = sub.add_parser("batch", help="Classify every image of a project whose classifier is validated.")
    run.add_argument("project", help="Project folder (contains project.json)")

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn
        from .app.server import create_app
        print(f"NucleiQuant is running: http://localhost:{args.port}", flush=True)
        uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
        return 0

    if args.command == "batch":
        from .api import Session
        from .jobs import JobManager
        session = Session(JobManager())
        session.open_project(os.path.abspath(args.project))
        job = session.start_batch()
        last = ""
        while True:
            j = session.jobs.get(job["id"])
            if j["message"] != last:
                print(f"[{j['progress'] * 100:5.1f}%] {j['message']}", flush=True)
                last = j["message"]
            if j["status"] in ("done", "error", "cancelled"):
                break
            time.sleep(0.5)
        if j["status"] != "done":
            print("Failed:", j["error"], file=sys.stderr)
            return 1
        print("Excel file:", j["result"]["excel"])
        return 0


if __name__ == "__main__":
    sys.exit(main())
