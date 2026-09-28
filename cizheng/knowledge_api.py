"""Knowledge routes inherit the host application's local session middleware."""
from fastapi import APIRouter, Query

from .knowledge import KnowledgeDocumentIn, KnowledgeStore


def create_knowledge_router(knowledge: KnowledgeStore):
    router = APIRouter(prefix='/api/knowledge', tags=['knowledge'])

    def filters(institution, source_type, rights, review_status, scope, document_id=None):
        return {key: value for key, value in locals().items() if value is not None}

    @router.get('/sources')
    def sources(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                institution: str | None = Query(None, max_length=300),
                source_type: str | None = Query(None, max_length=100),
                rights: str | None = Query(None, max_length=100),
                review_status: str | None = Query(None, max_length=100),
                scope: str | None = Query(None, max_length=1500)):
        return knowledge.list_sources(filters(institution, source_type, rights, review_status, scope), limit, offset)

    @router.get('/sources/{document_id}')
    def source(document_id: str, revision: int | None = Query(None, ge=1)):
        return knowledge.source(document_id, revision)

    @router.get('/search')
    def search(q: str = Query(..., min_length=1, max_length=200), limit: int = Query(8, ge=1, le=20),
               institution: str | None = Query(None, max_length=300),
               source_type: str | None = Query(None, max_length=100),
               rights: str | None = Query(None, max_length=100),
               review_status: str | None = Query(None, max_length=100),
               scope: str | None = Query(None, max_length=1500),
               document_id: str | None = Query(None, max_length=100)):
        return knowledge.search(q, filters(institution, source_type, rights, review_status, scope, document_id), limit)

    @router.post('/documents', status_code=201)
    @router.post('/sources', status_code=201)
    @router.post('/import', status_code=201)
    def add_document(body: KnowledgeDocumentIn):
        return knowledge.add_document(body.model_dump())

    return router
