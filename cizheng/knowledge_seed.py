"""Install reviewed-by-project source summaries, never external pages or answers."""
import json
from pathlib import Path


def seed_knowledge(knowledge):
    path = Path(__file__).resolve().parent.parent / 'knowledge/seeds.json'
    if not path.exists():
        return 0
    existing = {(s['title'], s['institution'], s['source_url']) for s in knowledge.list_sources(limit=500)['sources']}
    count = 0
    for body in json.loads(path.read_text()):
        identity = (body['title'], body['institution'], body['source_url'])
        if identity in existing:
            continue  # A user's changed edition is not overwritten by startup.
        knowledge.add_document(body)
        existing.add(identity); count += 1
    return count
