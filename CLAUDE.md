@AGENTS.md

## Notes for Claude Code

- There is no local Python environment: run Python through the Docker image
  (`./run_container.sh exec …`, `./run_container.sh test`). The host has an NVIDIA GPU.
- After changing Python code, restart the app container; frontend files are served live.
- Check UI changes in a real browser with `tests/e2e/run_walkthrough.sh` (it also refreshes
  the screenshots used by the docs) rather than by reading code alone.
- After any frontend edit, run `tests/e2e/check_modules.py` (syntax check in Chromium).
- Keep code comments short and descriptive, and user-facing text plain and jargon-free.
- Never commit, tag or push: the user does all git operations (even "restore point" commits).
- Every change set: say why and name its weaknesses to the user, and record it in
  `PROJECT.md` (decision log), plus AGENTS.md / Readme.md / docs/user_guide.md as needed.
- The user works from a Mac over SSH (VS Code Remote-SSH): local URLs need port forwarding
  (PORTS tab › Forward a Port › 8765).
