from __future__ import annotations
import json
from typing import Optional, TYPE_CHECKING
from attr import define, field
from griptape import utils
from griptape.artifacts import InfoArtifact, BaseArtifact
from griptape.tasks import PromptTask, ActionSubtask
from griptape.tools import BaseTool
from griptape.utils import J2
from griptape.mixins import ActionSubtaskOriginMixin

if TYPE_CHECKING:
    from griptape.memory import TaskMemory
    from griptape.structures import Structure


@define
class ToolTask(PromptTask, ActionSubtaskOriginMixin):
    tool: BaseTool = field(kw_only=True)
    subtask: Optional[ActionSubtask] = field(default=None, kw_only=True)
    task_memory: Optional[TaskMemory] = field(default=None, kw_only=True)

    def __attrs_post_init__(self) -> None:
        if self.task_memory is not None:
            self.set_default_tools_memory(self.task_memory)
        if self.tool.xml_functions_calling:
            self.xml_functions_calling = True

    def preprocess(self, structure: Structure) -> ToolTask:
        super().preprocess(structure)

        if self.task_memory is None and structure.task_memory is not None:
            self.set_default_tools_memory(structure.task_memory)

        return self

    def default_system_template_generator(self, _: PromptTask) -> str:
        action_schema = (
            utils.schema_to_xml(self.tool.schema())
            if self.xml_functions_calling
            else utils.minify_json(json.dumps(self.tool.schema()))
        )

        return J2("tasks/tool_task/system.j2").render(
            rulesets=J2("rulesets/rulesets.j2").render(rulesets=self.all_rulesets),
            action_schema=action_schema,
            meta_memory=J2("memory/meta/meta_memory.j2").render(meta_memories=self.meta_memories),
            xml_functions_calling=self.xml_functions_calling,
        )

    def run(self) -> BaseArtifact:
        prompt_output = self.prompt_driver.run(prompt_stack=self.prompt_stack).to_text()

        subtask = self.add_subtask(ActionSubtask(f"Action: {prompt_output}"))

        subtask.before_run()
        subtask.run()
        subtask.after_run()

        if subtask.output:
            self.output = subtask.output
        else:
            self.output = InfoArtifact("No tool output")

        return self.output

    def find_tool(self, tool_name: str) -> BaseTool:
        if self.tool.name == tool_name:
            return self.tool
        else:
            raise ValueError(f"Tool with name {tool_name} not found.")

    def find_memory(self, memory_name: str) -> TaskMemory:
        raise NotImplementedError("ToolTask does not support Task Memory.")

    def find_subtask(self, subtask_id: str) -> ActionSubtask:
        if self.subtask and self.subtask.id == subtask_id:
            return self.subtask
        else:
            raise ValueError(f"Subtask with id {subtask_id} not found.")

    def add_subtask(self, subtask: ActionSubtask) -> ActionSubtask:
        self.subtask = subtask
        self.subtask.attach_to(self)

        return self.subtask

    def set_default_tools_memory(self, memory: TaskMemory) -> None:
        self.task_memory = memory

        if self.task_memory:
            if self.tool.input_memory is None:
                self.tool.input_memory = [self.task_memory]
            if self.tool.output_memory is None and self.tool.off_prompt:
                self.tool.output_memory = {getattr(a, "name"): [self.task_memory] for a in self.tool.activities()}
