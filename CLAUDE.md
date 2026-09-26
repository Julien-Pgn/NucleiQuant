@AGENTS.md

## Notes for Claude Code

- There is no local Python environment: run Python through the Docker image
  (`./run_container.sh exec …`, `./run_container.sh test`). The host has an NVIDIA GPU.
- After changing Python code, restart the app container; frontend files are served live.
- Check UI changes in a real browser with `tests/e2e/run_walkthrough.sh` (it also refreshes
  the screenshots used by the docs) rather than by reading code alone.
- Keep code comments short and descriptive, and user-facing text plain and jargon-free.
- Don't commit or push unless asked.
