from enum import Enum


class AgentName(str, Enum):
    PLANNING  = "PlanningAgent"
    RESEARCH  = "ResearchAgent"
    SYNTH     = "SynthAgent"


class AgentType(str, Enum):
    PLANNING  = "planning"
    RESEARCH  = "research"
    SYNTH     = "synth"
