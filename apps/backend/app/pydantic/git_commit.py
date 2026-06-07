from pydantic import BaseModel
from datetime import datetime

class GitCommitDetail(BaseModel):
    sha: str
    author_name: str
    author_email: str
    commit_datetime: datetime
    message: str
    files_modified: list[str]
