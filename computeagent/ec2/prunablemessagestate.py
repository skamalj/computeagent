from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from typing_extensions import Annotated, TypedDict


class Reducer:
    def __init__(self, min_messages=0, max_messages=None):
        super().__init__()
        self.min_messages = min_messages
        self.max_messages = max_messages

    def reduce_messages(self, messages=[], message=None):
        messages = messages + message
        print(len(messages))
        if self.max_messages is None or len(messages) <= self.max_messages:
            return messages
        # Identify AIMessage and HumanMessage indices to prune
        to_delete = set()
        ai_human_indices = [i for i, msg in enumerate(messages) if isinstance(msg, (AIMessage, HumanMessage))]
        print("############################")
        # Calculate excess messages to remove
        excess_count = len(ai_human_indices) - self.max_messages

        # Loop through excess AI and Human messages to delete
        for i in ai_human_indices[:excess_count]:
            to_delete.add(i)

            # If AIMessage, find and mark associated ToolMessages
            if isinstance(messages[i], AIMessage):
                tool_call_id = messages[i].tool_call_id
                for j in range(i + 1, len(self.messages)):
                    if isinstance(messages[j], ToolMessage) and messages[j].tool_call_id == tool_call_id:
                        to_delete.add(j)

        # Delete messages in reverse order to avoid index shifting
        for idx in sorted(to_delete, reverse=True):
            print(messages[idx])
            del messages[idx]
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

def node(state:  PrunableMessageState):
    new_message = AIMessage(random.choice(random_messages))
    return {"messages": [new_message, new_message, new_message, new_message]}

graph_builder = StateGraph(PrunableMessageState)
graph_builder.add_node(node)
graph_builder.set_entry_point("node")
graph = graph_builder.compile()

from langchain_core.messages import HumanMessage

result = graph.invoke({"messages": [HumanMessage("Hi")]})
print(result)