from datetime import datetime
from pathlib import Path
from typing import Generator

from decouple import config
from jvis.zotero.manager import ZoteroManager as _ZoteroManager
from sqlalchemy.orm import Session

from ktem.db.engine import engine


class ZoteroManager:
    def __init__(self, app):
        self._app = app
        self._zotero_manager = _ZoteroManager(
            api_key=config("ZOTERO_API_KEY", None),
            library_id=config("ZOTERO_LIBRARY_ID", None),
            tag=config("ZOTERO_TAG_NAME", None),
        )

        indexes = [
            index for index in self._app.index_manager.indices
            if index.name == "Zotero Collection"
        ]
        if len(indexes) != 1:
            raise ValueError("Zotero Collection index not found")
        self._index = indexes[0]

    def sync(self):
        print("Syncing Zotero...")
        settings = self._app.default_settings.flatten()
        for i, (result, info) in enumerate(self.sync_with_zotero(settings)):
            print(f"{i} result: {result}")
            print(f"{i} info: {info}")
        print("Syncing Zotero completed")

    def sync_with_zotero(self, settings) -> Generator[tuple[str, str], None, None]:
        """Sync with Zotero"""
        index_fn = lambda file: self.index_fn(file, True, settings)
        yield from self._zotero_manager.sync(engine, index_fn)
        yield "", "Sync completed"

    def index_fn(
        self, file: Path, reindex: bool, settings
    ) -> Generator[tuple[str, str], None, None | list[str]]:
        """Index the file

        Args:
            file: path to the file to be indexed
            reindex: whether to reindex the files
            settings: the settings of the app
        """
        errors = self.validate([file])
        if errors:
            yield "", ""
            return

        # get the pipeline: UserID = 1 (admin)
        indexing_pipeline = self._index.get_indexing_pipeline(settings, 1)

        outputs, debugs = [], []
        # stream the output
        output_stream = indexing_pipeline.stream([file], reindex=reindex)
        try:
            while True:
                response = next(output_stream)
                if response is None:
                    continue
                if response.channel == "index":
                    if response.content["status"] == "success":
                        outputs.append(f"\u2705 | {response.content['file_name']}")
                    elif response.content["status"] == "failed":
                        outputs.append(
                            f"\u274c | {response.content['file_name']}: "
                            f"{response.content['message']}"
                        )
                elif response.channel == "debug":
                    debugs.append(response.text)
                yield "\n".join(outputs), "\n".join(debugs)
        except StopIteration as e:
            results, index_errors, docs = e.value
        except Exception as e:
            debugs.append(f"Error: {e}")
            yield "\n".join(outputs), "\n".join(debugs)
            return

        return results

    def validate(self, files: list[str]):
        """Validate if the files are valid"""
        paths = [Path(file) for file in files]
        errors = []
        if max_file_size := self._index.config.get("max_file_size", 0):
            errors_max_size = []
            for path in paths:
                if path.stat().st_size > max_file_size * 1e6:
                    errors_max_size.append(path.name)
            if errors_max_size:
                str_errors = ", ".join(errors_max_size)
                if len(str_errors) > 60:
                    str_errors = str_errors[:55] + "..."
                errors.append(
                    f"Maximum file size ({max_file_size} MB) exceeded: {str_errors}"
                )

        if max_number_of_files := self._index.config.get("max_number_of_files", 0):
            with Session(engine) as session:
                current_num_files = session.query(
                    self._index._resources["Source"].id
                ).count()
            if len(paths) + current_num_files > max_number_of_files:
                errors.append(
                    f"Maximum number of files ({max_number_of_files}) will be exceeded"
                )

        return errors