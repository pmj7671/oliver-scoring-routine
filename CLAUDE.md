# Oliver Scoring Routine

## Python Development Environment

### Package Manager: uv

This project uses [uv](https://docs.astral.sh/uv/) for Python package and environment management.

### Initial Setup

Install uv (if not already installed):
```powershell
pip install uv
# or via the standalone installer:
# powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Create and activate the virtual environment:
```powershell
uv venv .venv
.venv\Scripts\Activate.ps1
```

Install project dependencies:
```powershell
uv pip install -r requirements.txt
# or, if using pyproject.toml:
uv pip install -e .
```

### Daily Workflow

Activate the environment before working:
```powershell
.venv\Scripts\Activate.ps1
```

Add a new dependency:
```powershell
uv pip install <package>
uv pip freeze > requirements.txt   # update the lockfile
```

Run a script:
```powershell
uv run python main.py
# or, with the venv active:
python main.py
```

### Virtual Environment Notes

- The `.venv` directory is local-only and should be listed in `.gitignore`.
- Always prefer `uv pip install` over plain `pip install` to keep installs fast and reproducible.
- Use `uv pip compile requirements.in > requirements.txt` if you maintain an unpinned input file.

### Common Commands

| Task | Command |
|---|---|
| Create venv | `uv venv .venv` |
| Activate venv | `.venv\Scripts\Activate.ps1` |
| Install deps | `uv pip install -r requirements.txt` |
| Add package | `uv pip install <pkg>` |
| List installed | `uv pip list` |
| Run script | `uv run python <script>.py` |
| Deactivate | `deactivate` |
