from enum import Enum


class AgentName(str, Enum):
    RESEARCH = "ResearchAgent"


class AgentType(str, Enum):
    RESEARCH = "research"
    ANSWER   = "answer"
