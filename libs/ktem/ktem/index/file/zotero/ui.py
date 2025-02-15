from typing import Generator

import gradio as gr
from theflow.settings import settings as flowsettings

from ..ui import FileIndexPage

chat_input_focus_js = """
function() {
    let chatInput = document.querySelector("#chat-input textarea");
    chatInput.focus();
}
"""


class ZoteroIndexPage(FileIndexPage):
    def __init__(self, app, index):
        # Initialize our own attributes before calling parent's init
        self._last_sync_time = None
        self._index = index
        
        # Then call parent's init
        # This will call on_building_ui
        super().__init__(app, index)

    def action_instruction(self) -> str:
        msgs = []

        msgs.append("### Sync with Zotero")
        last_sync_time = "Never" if self._last_sync_time is None else self._last_sync_time
        msgs.append(f"- Last sync time: {last_sync_time}")

        if msgs:
            return "\n".join(msgs)

        return ""

    def on_building_ui(self):
        """Build the UI of the app"""
        with gr.Row():
            with gr.Column(scale=1):
                with gr.Column() as self.upload:
                    with gr.Tab("Actions"):
                        msg = self.action_instruction()
                        if msg:
                            gr.Markdown(msg)

                        self.sync_button = gr.Button(
                            "Sync with Zotero", variant="primary"
                        )

                        self.reindex_button = gr.Button(
                            "Reindex Selected File", variant="secondary"
                        )


            with gr.Column(scale=4):
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

    def index_fn(
        self, files, urls, reindex: bool, settings, user_id
    ) -> Generator[tuple[str, str], None, None]:
        """Upload and index the files

        Args:
            files: the list of files to be uploaded
            urls: list of web URLs to be indexed
            reindex: whether to reindex the files
            selected_files: the list of files already selected
            settings: the settings of the app
        """
        if urls:
            files = [it.strip() for it in urls.split("\n")]
            errors = []
        else:
            if not files:
                gr.Info("No uploaded file")
                yield "", ""
                return

            files = self._may_extract_zip(files, flowsettings.KH_ZIP_INPUT_DIR)

            errors = self.validate(files)
            if errors:
                gr.Warning(", ".join(errors))
                yield "", ""
                return

        gr.Info(f"Start indexing {len(files)} files...")

        # get the pipeline
        indexing_pipeline = self._index.get_indexing_pipeline(settings, user_id)

        outputs, debugs = [], []
        # stream the output
        output_stream = indexing_pipeline.stream(files, reindex=reindex)
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
