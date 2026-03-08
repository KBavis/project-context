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

**Goal**: Update our current approach to focus more on the semantic relationship by using proper Embedding & to also account for specific tokens. Upon this, we should consider looking into using Agentic toolings as well so we can jump around in code files and understand the users question 

**Refactoring**
One key piece s that we may be able to remove CODE vs DOCS collecitons altogether now that they use same embedding, _and_ we may be able to also remove the query decomposition functionality. We can store everything in the same Chroma Collection since same embedding (chunking will still need to be determined by file type). We can use the `QueryFusionRetriever` with `num_queries=3` to decompose a query like _"How do we do chunking"_ into better questions 

**Implemetation**
- Change Embedding Collections to leverage BGE instead of BERT. This is because we need the embedding to understand that the users query is a _request for information_ and the code is the answer. BERT will typically only focus on the relationship between tokens 
- Utilize `QueryFusionRetriever` instead of `index.as_retriever` in our function `get_chunks()` in `ChunkingService` -- this willperform a _dual search_, finding code that performs tasks similar to the query, and BM25 Retriever which will find specific tokens 
- RRF (Reciporacl Rank Fusion) will combine results and returned highest ranked chunks 
- **NOTE**: We will need access to textnodes for BM25, so these need to be in memory instead of simply querying Chroma 

**Agentic Approach**
- Along with updating our Chunk retrieval flow via RAG, we should also consider making this Agentic RAG 
- This flow will leverage the `search_code` tool and find context it's looking for and determine if its enough to answer question 
- This would involve creating an _adjacnecy list_ with our code file content (i.e `FileContent` with FK to `File`)
- We should look into `pg_vector` from Llama Index and see if we need Chroma at all