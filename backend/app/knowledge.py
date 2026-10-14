import re
from sqlalchemy import select
from .models import Runbook, KnowledgeChunk
from .core import uid
from .ai import embed


def add_knowledge(db, body, source_type="runbook", source_id=None):
    if source_type == "runbook":
        existing = db.scalar(
            select(Runbook).where(
                Runbook.service_id == body["service_id"],
                Runbook.title == body["title"],
                Runbook.version == body["version"],
            )
        )
        if existing:
            return existing
        book = Runbook(id=uid(), **body)
        db.add(book)
        db.flush()
        source_id = book.id
    pieces = [p.strip() for p in re.split(r"(?m)(?=^#{1,3} )", body["content"]) if len(p.strip()) > 10]
    # Bound long headings without discarding any content.
    chunks = []
    for piece in pieces:
        words = piece.split()
        for i in range(0, len(words), 570):
            chunks.append((piece.splitlines()[0][:100], " ".join(words[i : i + 650])))
    vectors = embed([text for _, text in chunks])
    for (section, text), vector in zip(chunks, vectors):
        db.add(
            KnowledgeChunk(
                service_id=body["service_id"],
                source_type=source_type,
                source_id=source_id,
                section=section,
                version=body["version"],
                environment=body["environment"],
                text=text,
                embedding=vector,
            )
        )
    db.commit()
    return book if source_type == "runbook" else source_id


def retrieve(db, service, query, complete_runbook=False):
    vector = embed([query])[0]
    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    query = (
        select(KnowledgeChunk, distance.label("distance"))
        .where(KnowledgeChunk.service_id == service.id, KnowledgeChunk.environment == service.environment)
        .order_by(distance)
        .limit(6)
    )
    if complete_runbook:
        query = query.where(KnowledgeChunk.source_type == "runbook")
    rows = db.execute(query).all()
    if complete_runbook and rows:
        selected_source = rows[0][0].source_id
        rows = db.execute(
            select(KnowledgeChunk, distance.label("distance"))
            .where(
                KnowledgeChunk.service_id == service.id,
                KnowledgeChunk.environment == service.environment,
                KnowledgeChunk.source_type == "runbook",
                KnowledgeChunk.source_id == selected_source,
            )
            .order_by(distance)
        ).all()
    result = []
    for chunk, dist in rows:
        book = db.get(Runbook, chunk.source_id) if chunk.source_type == "runbook" else None
        result.append(
            {
                "chunk_id": chunk.id,
                "source_id": chunk.source_id,
                "source_type": chunk.source_type,
                "title": book.title if book else "Finalized incident history",
                "section": chunk.section,
                "version": chunk.version,
                "text": chunk.text,
                "distance": float(dist),
                "warning": "Runbook is outdated" if book and book.status == "outdated" else None,
            }
        )
    return result
