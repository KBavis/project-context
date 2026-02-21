import uvicorn
import os
from .base import create_app

app = create_app()

if __name__ == "__main__":
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    uvicorn.run(
        "app.main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=not debug_mode,  # disable reload when debugging (reload spawns subprocesses debugpy can't attach to)
        reload_excludes=[
            "tmp/code/**/*",   
            "tmp/docs/**/*",    
            "*.pyc",
            "__pycache__/*"
        ]
    )
