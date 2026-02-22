import uvicorn
import os
from .base import create_app

app = create_app()

if __name__ == "__main__":
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"

    # Only watch the app/ source directory.
    # Using __file__ makes this robust regardless of CWD (local vs. Docker).
    # tmp/, .venv/, and any other runtime-written directories are completely
    # invisible to watchfiles — no glob pattern needed.
    app_source_dir = os.path.dirname(os.path.abspath(__file__))

    uvicorn.run(
        "app.main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=not debug_mode,  # disable reload when debugging (reload spawns subprocesses debugpy can't attach to)
        reload_dirs=[app_source_dir],  # ONLY watch app/ source, not tmp/ or anything else
    )
