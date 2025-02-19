from datetime import datetime
from pathlib import Path
from typing import Generator

from decouple import config
import gradio as gr
from jvis.zotero.db import ZoteroSyncs
from jvis.zotero.manager import ZoteroManager
from theflow.settings import settings as flowsettings
from sqlalchemy import select
from sqlalchemy.orm import Session
from ktem.db.engine import engine

from ..ui import FileIndexPage


class ZoteroIndexPage(FileIndexPage):
    def __init__(self, app, index):
        # Initialize our own attributes before calling parent's init
        self._index = index
        self._zotero_manager = ZoteroManager(
            api_key=config("ZOTERO_API_KEY", None),
            library_id=config("ZOTERO_LIBRARY_ID", None),
            tag=config("ZOTERO_TAG_NAME", None),
        )
        
        # Then call parent's init
        # This will call on_building_ui
        super().__init__(app, index)

    def on_building_ui(self):
        """Build the UI of the app"""
        with Session(engine) as session:
            last_sync = session.execute(
                select(ZoteroSyncs.sync_finished_at)
                .where(ZoteroSyncs.sync_finished_at.is_not(None))
                .order_by(ZoteroSyncs.sync_finished_at.desc())
                .limit(1)
            ).scalar()

        with gr.Row():
            with gr.Column(scale=1):
                with gr.Column() as self.upload:
                    with gr.Tab("Actions"):
                        self.sync_last_time = gr.State(last_sync)

                        gr.Markdown("### Sync with Zotero")
                        self.sync_last_time_display = gr.Markdown(
                            "- Last sync time: Never" if last_sync is None else f"- Last sync time: {last_sync.strftime('%Y-%m-%d %H:%M:%S')}"
                        )

                        self.sync_button = gr.Button(
                            "Sync with Zotero", variant="primary"
                        )

                        self.reindex_button = gr.Button(
                            "Reindex Selected File", variant="secondary", interactive=False
                        )


            with gr.Column(scale=4):
                with gr.Column(visible=False) as self.sync_progress_panel:
                    gr.Markdown("## Sync Progress")
                    with gr.Row():
                        self.sync_result = gr.Textbox(
                            lines=1, max_lines=20, label="Sync result"
                        )
                        self.sync_info = gr.Textbox(
                            lines=1, max_lines=20, label="Sync info"
                        )
                    self.btn_close_sync_progress_panel = gr.Button(
                        "Clear Sync Info and Close",
                        variant="secondary",
                        elem_classes=["right-button"],
                    )

                with gr.Tab("Files"):
                    self.render_file_list()

                with gr.Tab("Groups"):
                    self.render_group_list()

    def on_register_events(self):
        """Register all events to the app"""
        self.deselect_button.click(
            fn=lambda: (None, self.selected_panel_false),
            inputs=[],
            outputs=[self.selected_file_id, self.selected_panel],
            show_progress="hidden",
        ).then(
            fn=self.file_selected,
            inputs=[self.selected_file_id],
            outputs=[
                self.chunks,
                self.deselect_button,
                self.delete_button,
                self.download_single_button,
                self.chat_button,
            ],
            show_progress="hidden",
        )

        self.chat_button.click(
            fn=self.set_file_id_selector,
            inputs=[self.selected_file_id],
            outputs=[
                self._index.get_selector_component_ui().selector,
                self._index.get_selector_component_ui().mode,
                self._app.tabs,
            ],
        )

        self.download_all_button.click(
            fn=self.download_all_files,
            inputs=[],
            outputs=self.download_all_button,
            show_progress="hidden",
        )

        self.download_single_button.click(
            fn=self.download_single_file,
            inputs=[self.is_zipped_state, self.selected_file_id],
            outputs=[self.is_zipped_state, self.download_single_button],
            show_progress="hidden",
        )

        self.btn_close_sync_progress_panel.click(
            fn=lambda: (gr.update(visible=False), "", ""),
            outputs=[self.sync_progress_panel, self.sync_result, self.sync_info],
        )

        self.file_list.select(
            fn=self.interact_file_list,
            inputs=[self.file_list],
            outputs=[self.selected_file_id, self.selected_panel],
            show_progress="hidden",
        ).then(
            fn=self.file_selected,
            inputs=[self.selected_file_id],
            outputs=[
                self.chunks,
                self.deselect_button,
                self.delete_button,
                self.download_single_button,
                self.chat_button,
            ],
            show_progress="hidden",
        )

        self.group_list.select(
            fn=self.interact_group_list,
            inputs=[self.group_list_state],
            outputs=[self.group_label, self.group_name, self.group_files],
            show_progress="hidden",
        ).then(
            fn=lambda: (
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=True),
                gr.update(visible=True),
            ),
            outputs=[
                self._group_info_panel,
                self.group_add_button,
                self.group_close_button,
                self.group_delete_button,
                self.group_chat_button,
            ],
        )

        self.filter.submit(
            fn=self.list_file,
            inputs=[self._app.user_id, self.filter],
            outputs=[self.file_list_state, self.file_list],
            show_progress="hidden",
        )

        self.group_add_button.click(
            fn=lambda: [
                gr.update(visible=False),
                gr.update(value="### Add new group"),
                gr.update(visible=True),
                gr.update(value="", interactive=True),
                gr.update(value=[]),
            ],
            outputs=[
                self.group_add_button,
                self.group_label,
                self._group_info_panel,
                self.group_name,
                self.group_files,
            ],
        )

        self.group_chat_button.click(
            fn=self.set_group_id_selector,
            inputs=[self.group_name],
            outputs=[
                self._index.get_selector_component_ui().selector,
                self._index.get_selector_component_ui().mode,
                self._app.tabs,
            ],
        )

        onGroupSaved = (
            self.group_save_button.click(
                fn=self.save_group,
                inputs=[self.group_name, self.group_files, self._app.user_id],
            )
            .then(
                self.list_group,
                inputs=[self._app.user_id, self.file_list_state],
                outputs=[self.group_list_state, self.group_list],
            )
            .then(
                fn=lambda: gr.update(visible=False),
                outputs=[self._group_info_panel],
            )
        )
        self.group_close_button.click(
            fn=lambda: [
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
            ],
            outputs=[
                self.group_add_button,
                self._group_info_panel,
                self.group_close_button,
                self.group_delete_button,
                self.group_chat_button,
            ],
        )
        onGroupDeleted = self.group_delete_button.click(
            fn=self.delete_group,
            inputs=[self.group_name],
        ).then(
            self.list_group,
            inputs=[self._app.user_id, self.file_list_state],
            outputs=[self.group_list_state, self.group_list],
        )

        for event in self._app.get_event(f"onFileIndex{self._index.id}Changed"):
            onGroupDeleted = onGroupDeleted.then(**event)
            onGroupSaved = onGroupSaved.then(**event)

        onSynced = self.sync_button.click(
            fn=lambda: gr.update(interactive=False),
            outputs=[self.sync_button],
        ).then(
            fn=lambda: gr.update(visible=True),
            outputs=[self.sync_progress_panel],
        ).then(
            fn=self.sync_with_zotero,
            inputs=[self._app.settings_state],
            outputs=[self.sync_result, self.sync_info, self.sync_last_time, self.sync_last_time_display],
            concurrency_limit=1,
        ).then(
            fn=lambda: gr.update(interactive=True),
            outputs=[self.sync_button],
        )

        syncedEvent = onSynced.then(
            fn=self.list_file,
            inputs=[self._app.user_id, self.filter],
            outputs=[self.file_list_state, self.file_list],
            concurrency_limit=20,
        )
        for event in self._app.get_event(f"onFileIndex{self._index.id}Changed"):
            syncedEvent = syncedEvent.then(**event)

        self.reindex_button.click(
            fn=self.reindex_file,
            inputs=[self.selected_file_id],
            outputs=[],
        )

    def sync_with_zotero(self, settings):
        """Sync with Zotero"""
        gr.Info(f"Starting synchronization with Zotero...")

        index_fn = lambda file: self.index_fn(file, True, settings)
        cum_result, cum_info = [], []
        _iter = self._zotero_manager.sync(engine, index_fn)
        for result, info in _iter:
            cum_result.append(result)
            cum_info.append(info)
            yield "\n".join(cum_result), "\n".join(cum_info), None, None

        cum_info.append("Sync completed")
        current_time = datetime.now()
        yield (
            "\n".join(cum_result),
            "\n".join(cum_info),
            current_time,
            f"- Last sync time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}",
        )

    def reindex_file(self, file_id):
        """Reindex the selected file"""
        gr.Info(f"Starting to reindex file...")
        with Session(engine) as session:
            source = session.execute(
                select(self._index._resources["Source"]).where(
                    self._index._resources["Source"].id == file_id
                )
            ).first()

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
            gr.Warning(", ".join(errors))
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

        n_successes = len([_ for _ in results if _])
        if n_successes:
            gr.Info(f"Successfully index {n_successes} files")
        n_errors = len([_ for _ in errors if _])
        if n_errors:
            gr.Warning(f"Have errors for {n_errors} files")

        return results
