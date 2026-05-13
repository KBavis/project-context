from collections import defaultdict
from llama_index.core.tools import FunctionTool
from uuid import UUID
from typing import Callable, Any

from app.llm import LLMBase
from app.models.data_source import DataSource
from app.data_providers import DataProvider
from app.services.chunk_retrieval import ChunkRetrievalService


class Tools:
    """
    Class to store all of the Tooling that will be available to the Agent during a particular 
    Agentic Worfklow execution 

    TODO: This is exclusively internal tooling at the moment, it may make since to include MCP here as well to just 
    have a nice way of interfacing the tooling available to the Agent 
    """

    def __init__(
        self, 
        data_sources: list[DataSource], 
        project_id: UUID, 
        llm: LLMBase,
        chunk_retrieval_svc: ChunkRetrievalService
    ):
        self.data_sources = data_sources
        self.project_id = project_id
        self.llm = llm
        self.chunk_retrieval_svc = chunk_retrieval_svc

        self._data_source_tools: defaultdict[UUID, list[FunctionTool]] = defaultdict(list)
        self._project_wide_tools: list[FunctionTool] = []

        self._init_tooling() 


    async def get_internal_tools(self, data_source_id = None) -> list[FunctionTool] | None:
        """
        High level function to retrieve all of the internal tooling that has been configured for Agent Workflow Execution
        """
        if not data_source_id:
            return self._project_wide_tools + [tool for tools in self._data_source_tools.values() for tool in tools] 
        
        return self._project_wide_tools + self._data_source_tools.get(data_source_id, [])

    
    def _init_tooling(self):
        """
        Function to leverage the provided DataSources and selected Project to initalize the tooling 
        that should be available during Agentic Workflow 
        """

        # Step 1. Initalize DataSource specific internal tooling based on the Data Provider 
        for data_source in self.data_sources:

            data_provider = DataProvider.from_provider(data_source)
            
            view_file_tool = self._build_function_tool(
                async_fn=data_provider.view_file, 
                function_name="view_file", 
                description=(
                    "View the contents of a particular file in the given DataSource. " +
                    "The file_path argument MUST begin with a forward slash '/' if not the root directory" 
                )
            )
            list_directory_tool = self._build_function_tool(
                async_fn=data_provider.list_directory, 
                function_name="list_directory", 
                description=(
                    "List the contents of a particular directory in the given DataSource. " +
                    "The path argument MUST begin with a forward slash '/' if not the root directory. " + 
                    "If it's the root directory, pass an empty string '' as the path argument"
                )
            )

            self._data_source_tools[data_source.id] = [view_file_tool, list_directory_tool]
        

        # Step 2. Initalize Project-wide internal tooling that can be leveraged for any Data Source 
        semantic_search_tool = self._build_function_tool(
            async_fn=self._semantic_search_wrapper,
            function_name="semantic_search",
            description=(
                "Use this tool to search the codebase or documentation based on conceptual or semantic meaning, "
                "rather than exact keyword matches. Best used for questions like 'How does the authentication flow work?' "
                "or 'Where is data ingested?'. This will retrieve the most conceptually relevant chunks of text."
            )
        )

        grep_search_tool = self._build_function_tool(
            async_fn=self._grep_search_wrapper,
            function_name="grep_search",
            description=(
                "Use this tool to find EXACT keyword matches or variable names in the codebase or documentation. "
                "The key_word argument accepts Postgres POSIX Regular Expressions. "
                "CRITICAL: To catch variations (plurals, casing, spacing), you SHOULD use regex patterns. "
                "For example, to find 'Ingestion Job', pass 'ingestion\\s*jobs?' to catch all variations."
            )
        )

        self._project_wide_tools = [semantic_search_tool, grep_search_tool]
    

    #######################################
    ### Wrapper Functions for Tools
    ######################################

    async def _grep_search_wrapper(self, key_word: str, data_source_ids: list[str] | None = None):
        """
        Wrapper function for leveraging grep search functionality, while injecting the variables 
        that the Agent is unware of 

        Args:
            key_word: The User's keyword to grep search against
            data_source_ids: The Data Source IDs to grep search against. If None, will default to all Data Sources in the Project 

        Returns:
            list[str]: The metadata of the grep searched chunks 
        """ 

        if not data_source_ids:
            data_source_ids = [str(ds.id) for ds in self.data_sources]
        
        return await self.chunk_retrieval_svc.grep_search(
            key_word,
            self.project_id,
            data_source_ids=data_source_ids
        )

    async def _semantic_search_wrapper(self, query: str, data_source_ids: list[str] | None = None):
        """
        Wrapper function for leveraging semantic search functionality, while injecting the variables 
        that the Agent is unware of 

        Args:
            query: The User's query to semantically search against
            data_source_ids: The Data Source IDs to semantically search against. If None, will default to all Data Sources in the Project 

        Returns:
            list[str]: The metadata of the semantically searched chunks 
        """ 

        if not data_source_ids:
            data_source_ids = [str(ds.id) for ds in self.data_sources]
        
        return await self.chunk_retrieval_svc.semantic_search(
            query,
            self.project_id,
            llm=self.llm,
            data_source_ids=data_source_ids
        )
    

    #######################################
    ### Tool Utility Functions 
    ######################################


    def _build_function_tool(self, async_fn: Callable[..., Any], function_name: str, description: str) -> FunctionTool:
        """
        Utility function to build a llama_index.core.tools.FunctionTool that can 
        be leverage by our Agentic Workflow 

        Args:
            async_fn: The function to be wrapped in a FunctionTool
            function_name: the function name 
            description: the description of the function
        """

        return FunctionTool.from_defaults(
            async_fn=async_fn,
            name=function_name,
            description=description
        )
            




    


