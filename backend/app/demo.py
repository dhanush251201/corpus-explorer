"""
Fixture data for DEMO_MODE. This module writes ONLY to an in-memory mongomock
instance - it is never given a real connection, and get_client() calls it only
when settings.DEMO_MODE is true. It is kept out of db.py so that the read-only
grep over the rest of the application returns nothing.
"""
import json, random
from datetime import datetime, timedelta

from .config import settings, BASE

FIXTURES = BASE / "fixtures" / "demo.json"


def seed(client):
    db = client[settings.DB_NAME]
    if FIXTURES.exists():
        data = json.loads(FIXTURES.read_text())
        for coll, docs in data.items():
            for d in docs:
                if isinstance(d.get("published_at"), str):
                    d["published_at"] = datetime.fromisoformat(d["published_at"])
            if docs:
                db[coll].insert_many(docs)
        return
    random.seed(11)
    db[settings.MASTER].insert_many([{
        "url": f"https://example.org/{i}", "title": f"Placeholder document {i}",
        "think_tank": "ECFR", "publication_group": "Commentary",
        "published_at": datetime(2022, 1, 1) + timedelta(days=i * 7),
        "article_text": "European strategic autonomy in defence policy. " * 40,
        "pdf_text": "", "authors": ["A. Author"], "source_file": "DEMO.json",
    } for i in range(60)])
