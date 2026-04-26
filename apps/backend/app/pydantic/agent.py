from enum import Enum

class AgentName(str, Enum):
    ORCHESTRATOR = "OrchestratorAgent"
    CODE = "CodeAgent"
    DOCS = "DocsAgent"
    SYNTH = "SynthAgent"


class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    CODE = "code"
    DOCS = "docs"
    SYNTH = "synth"

