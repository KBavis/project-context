# RAG Updates 

_NOTE_: We should look into **LangChain, DataConnectors from LlamaIndex, and AgenticRAG with LllamaIndex** 


## Overview 
Big issue with the RAG approach currently is that we don't have a sophisitcated way for the model to leverage the code base. We have ingested and chunked the code base,
but the mechanism for retrieving the necessary context to answer the users question comprehensively is not well defined. The semantic similarity between a question such as 
"What library is used for chunking" is typically not retrieving the relevant chunks as effectively as it should be. As a result of this, we need to implement a more 
sophisitcated way of giving the LLM the context it needs to comprehensively answer the users question. 


## Documentation 

**Goal:** Ensure that the Documentation retrieval is performing at a high level of accuracy. 

**Approach:** If there is some information that is well defined in a particular Document (even if its considered a relatively small portion), we should be able to 
retrieve that information with high accuracy. We should also have an effecitve ability to retrieve the most relevant Documents pertaining to a user's question 
_even if the Project has a large number of Documents chunked and stored_.

**Testing:** The way we can go about attempting this is by setting up a Project with a large number of Documents chunked and stored (such as some Opensource repository).
We should try and ask niche questions based on that Documentation and have some sort of metric as to how well the model is able to retrieve the relevant Documents. 

**Implementation:** In the case that it's not retrieving the relevant Documents at a high clip and answering the users quesiton comprehensively, we should try and rethink our chunking approach (i.e currently using Docling) and really dive deep into how the chunking is working. We should also ensure that the metadata we have stored is as rich as possible. Lastly, we should investigate how LlamaIndex & Chroma are being integrated and really understand how we can force this to be better .


## Code

**Goal:** Impelemnt some sort of agentic capabiltiies (similar to Claude Code / Copilot / etc) that our model can transverse the relevant files and get a good 
sense of where it needs to be looking based on users question. Allow for user to ask questions from a start file and have the model transverse the relevant files, 
and also simply be able to find files based on what the user is asking. 

**Approach:** 
1. Consildate the Chroma DB Collection to simply store Documentation chunks (remove references to CODE vs DOCS, update naming conventions)
2. Create new model that stores FileContent