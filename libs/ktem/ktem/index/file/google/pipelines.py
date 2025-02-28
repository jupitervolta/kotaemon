from typing import Optional

from decouple import config
from sqlalchemy.orm import Session

from kotaemon.base import RetrievedDocument
from ktem.db.models import engine, GoogleDocs
from ktem.index.file.pipelines import DocumentRetrievalPipeline


class GoogleDocumentRetrievalPipeline(DocumentRetrievalPipeline):
    """Retrieve documents from Google Docs"""

    def run(
        self,
        text: str,
        doc_ids: Optional[list[str]] = None,
        *args,
        **kwargs,
    ) -> list[RetrievedDocument]:
        """Retrieve document excerpts similar to the text

        Args:
            text: the text to retrieve similar documents
            doc_ids: list of document ids to constraint the retrieval
        """
        docs = super().run(text, doc_ids, *args, **kwargs)
        with Session(engine) as session:
            for doc in docs:
                file_id = doc.metadata["file_id"]
                item = session.query(GoogleDocs).filter(
                    GoogleDocs.file_id == file_id
                ).first()
                if item is None:
                    continue
                doc.metadata["url"] = f"https://drive.google.com/open?id={item.google_id}"
        return docs
