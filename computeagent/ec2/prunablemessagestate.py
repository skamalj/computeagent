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

        for i, msg in messages[1:excess_count]:
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

reducer_instance = Reducer(min_messages=3, max_messages=4)

class PrunableStateFactory:
    @staticmethod
    def create_prunable_state(min_messages: int, max_messages: int):
        reducer = Reducer(min_messages=min_messages, max_messages=max_messages)
        
        class PrunableMessageState(TypedDict):
            messages: Annotated[list, reducer.reduce_messages]

        return PrunableMessageState

PrunableMessageState = PrunableStateFactory.create_prunable_state(2, 3)   

from langgraph.graph import StateGraph
import random

random_messages = [
    "Hello there!",
    "How can I assist you today?",
    "I'm here to help!",
    "What's on your mind?",
    "Let's dive into it!"
]

def node(state):
    new_message = AIMessage(random.choice(random_messages))
    new_message2 = AIMessage(random.choice(random_messages))
    new_message3 = AIMessage(random.choice(random_messages))
    return {"messages": [new_message, new_message, new_message, new_message2, new_message3]}

graph_builder = StateGraph(PrunableMessageState)
graph_builder.add_node(node)
graph_builder.set_entry_point("node")
graph = graph_builder.compile()

from langchain_core.messages import HumanMessage

result = graph.invoke({"messages": [HumanMessage("Hi")]})
print(result)