import os
from datetime import datetime
from pathlib import Path

from .long_term import LongTermMemory
from . import integration_long_term
from . import store_sqlalchemy, model_openai, index_whoosh
from . import default
import chatwrap
import chatwrap.openaigpt, chatwrap.chatlog

logdir = Path("logs")
user_id = "jar"

store = default.get_store()
ltm = default.create_long_term(store=store)

files = list(logdir.glob("*.log"))
files.sort(key=lambda f: f.stat().st_mtime)

for file_path in files:
    basename = os.path.basename(file_path)

    existing = store.get_conversation(user_id, basename)
    if existing is not None:
        print(f"Skipping already ingested {basename}")
        continue

    print(f"Ingesting {basename}")
    integration_long_term.ingest_conversation(
        ltm, user_id=user_id,
        conversation_id=basename,
        messages=chatwrap.chatlog.load_log(None, file_path),
        started_at=datetime.strptime(basename[4:23], "%Y-%m-%d_%H-%M-%S"),
        ended_at=datetime.fromtimestamp(os.path.getmtime(file_path)),
    )

