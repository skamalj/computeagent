from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from typing_extensions import Annotated, TypedDict


class Reducer:
    def __init__(self, min_messages=0, max_messages=None):
        super().__init__()
        self.min_messages = min_messages
        self.max_messages = max_messages

    def reduce_messages(self, messages=[], message=None):
        messages = messages + message
        if self.max_messages is None or len(messages) <= self.max_messages:
            return messages
        # Identify AIMessage and HumanMessage indices to prune
        to_delete = set()
        # Calculate excess messages to remove
        excess_count = len(messages) - self.min_messages

        for i, msg in enumerate(messages[1:excess_count], start=1):
            if isinstance(msg, (AIMessage, HumanMessage)):
                to_delete.add(i)


            # If AIMessage, find and mark associated ToolMessages
            if isinstance(messages[i], AIMessage) and hasattr(messages[i], 'tool_calls'):
                for tool_call in messages[i].tool_calls:
                    tool_call_id = tool_call.get("id")
                    for j in range(i + 1, len(messages)):
                        if isinstance(messages[j], ToolMessage) and messages[j].tool_call_id == tool_call_id:
                            to_delete.add(j)

        # Delete messages in reverse order to avoid index shifting
        for idx in sorted(to_delete, reverse=True):
            del messages[idx]
        print(f"Reduced messages from {len(messages) + excess_count} to {len(messages)}: {messages}")
        return messages

class PrunableStateFactory:
    @staticmethod
    def create_prunable_state(min_messages: int, max_messages: int):
        reducer = Reducer(min_messages=min_messages, max_messages=max_messages)
        
        class PrunableMessageState(TypedDict):
            messages: Annotated[list, reducer.reduce_messages]

        return PrunableMessageState
