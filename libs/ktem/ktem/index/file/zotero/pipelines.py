from typing import Optional

from decouple import config
from sqlalchemy.orm import Session

from kotaemon.base import RetrievedDocument
from ktem.db.models import engine, ZoteroItems
from ktem.index.file.pipelines import DocumentRetrievalPipeline

ZOTERO_LIBRARY_ID = config("ZOTERO_LIBRARY_ID")


class ZoteroDocumentRetrievalPipeline(DocumentRetrievalPipeline):
    """Retrieve documents from Zotero"""

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
                items = session.query(ZoteroItems).filter(
                    ZoteroItems.file_id == file_id
                ).first()
                if items is None:
                    continue
                doc.metadata["url"] = f"https://www.zotero.org/groups/{ZOTERO_LIBRARY_ID}/jvolta/items/{items.key}"
        return docs
