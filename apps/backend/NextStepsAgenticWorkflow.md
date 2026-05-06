# **Next Steps: Agentic Workflow**



##### Current State

* Insights into the Agentic Workflow as it's being performed (i.e tools being used, models basic thinking, etc)
* Ability to leverage the MCP tools that are associated to the Project tied to a particular Conversation (all MCP tools are provided)
* Unable to utilize any logic surrounding our ingested data in Chroma DB / internal tooling capabilities
* Ability to answer questions is a bit "un-deterministic" -- the flow is entirely dependent on the models capabilities and it's ability to think through next steps based on the workflow outlined in the system prompt files
* Unable to leverage basically any of the Documentation capabilities, aside from **.md** files that are within a Repository
* Some basic insights into the decisions and thinking being performed by model
* **Heavy token usage,** not very cost efficient whatsoever
* Citations that don't typically link to the exact files and locations in the files where the information was retrieved
* No "over-arching" search capabilities, everything is basically just brute force and the model making "best-guesses" as to where it should look for next, and whether or not it's achieved it's goal
* Unable to filter searching capabilities on a "per-Project" basis, as of now, the entire Data Source is game when searching for the answer to a question
* Merging the contexts of a particular Data Source (i.e a repository) and the corresponding Project's outcome on that Data Source (i.e **Microservice A** is the data source, but the **Project X** was used to change **Y** aspect about this **Data Source)**







##### Next Steps (Non-Prioritized)



###### 

###### **Researching Optimizations in Token Usage**



* **Selective Tool Usage**

  * ***Current:***

    * As of now, we will basically specify all tools associated with the MCP servers that are tied to the Data Sources used by the Project

      * *EX)* If I have a *Project* with three separate *DataSources* (i.e Confluence, and two separate Repositories), where each of these *DataSource's* have corresponding MCP Server
    * The tools and their corresponding descriptions are then appended throughout the context of our Agentic Workflow, which ***eats*** into our total token usage and our context window
  * ***Goals:***

    * 1\) *Deduplicate MCP Tooling -* if we have two distinct DataSources configured for a particular Project, that both leverage the same *GitHub MCP* server, then we only need this set of tools *a single time*
    * 2\) *Selective MCP Tooling -* certain user's questions will only require certain tools (or even Data Sources) to be leveraged. We should be able to filter down the list a bit for the particular question
* **Structured Agentic Flow (Architecture Shift)**

  * ***Current:***

    * The only "structure" in terms of the flow of events that we have in our Agentic Workflow is through our System Prompts. This results in the model attempting to Brute Force answer a user's particular question without ever having a super clear plan as to "how"
  * ***Goals:***

    * 1\) *RESEARCH:* The first step here will be determining how we can add a bit more structure and potential user input into how a model is going about answering a particular user's question

      * **idea:**

        * 1\) Diagnosis Phase -- understanding user's question, intent, what pieces of information would be relevant in answering the user's question, what data sources are required, etc
        * 2\) Planning Phase -- human in the loop if the investigation will be deep research (simple Q \& A likely not needed). Give's the user a sense of being in the loop to help address situations where the model is hallucinating
        * 3\) Research Phase -- model is investigating the data sources and trying to obtain necessary context in the most efficient possible manner
        * 4\) Answering Phase -- model formats retrieved context and correctly articulates the answer, while also providing the relevant citations for the user to continue their investigation more
    * 2\) *IMPLEMENT:* once we have determined a correct methodology to add some structure, we should update our Agentic Workflow to account for this
  * **Agent Updates**

    * Along with these UI changes, it feels like we could better update our overall **Workflow** to be different from the current "Orchestrator" <--> "Docs / Code" to "Synthesis" Pipelien

      * Is this increase bloat in terms of Token Usage?
      * How does this shift based on above planning? 
* **Leveraging Hybrid Approach -- Chroma DB \& Agentic Approach -- Internal Tooling Capabilities**

  * ***Current:***

    * As of now, we really focus solely on the idea that the Agent should simply use the provided Data Sources in the system prompts and corresponding MCP tooling to determine the answer to the user's question
    * This section ties into the above architecture proposed changes
  * ***Goal:***

    * Extract relevant files or pieces of information called out by the RAG approach (i.e we query our Chroma DB for a project and get access to a bunch of chunks (and corresponding files) that could be used as "starting" point for context searching if needed
    * **grep** functionality, super fast lookup for specific key words or pieces of information, just a way to allow for the project to find pieces of information spanning across multiple data sources
    * Overarching file structure understanding of a particular data source so the model knows where to look



###### 

###### **Expanding on Data Source Capabilities**



* **Confluence**

  * One of the key aspects that I want to integrate is the ability to transverse through relevant Confluence spaces in a similar way an Agent would do for a repository 
  * For example, if I have a Data Source setup and the space is our High Level Project Space, then all of the sub-pages are all fair game in terms of the Agent getting access to 
* **Manual File Uploads** (i.e **PDF's, DOCX, etc)**

  * Occasionally, some relevant information may not be accessible on a particular Data Provider
  * We may want to upload a "one-off" file that we associate to a particular Project, where in the future, I could navigate to this Project and be able to Query it directly 
* **Webex** 

  * There is likely a ton of value in being able to ingest and interpret some of the Webex Messages that have been stored in Chat 
  * A lot of questions have been asked in the past and then re-asked in the future 
  * Having some sort of ability to diagnose these relevant pieces of information from important Webex Spaces will be super useful in the future for Developers in order to no longer need to re-ask these questions 

&#x20; 



###### **User Interface Updates**



* **UI Messages** 

  * Update the "send message" input box to account for multiple line messages if user sends a lot of details 
  * Update UI Messages in chat to account for new line characters in model response 
* **Data Source Creation**

  * Specifying the "type" of data source when we are creating one via the UI is not currently a thing 





###### **Citations** 

* **Output Format** 

  * Direct links to the file that are leveraged by model when answering question 
  * If relevant chunks are retrieved via our Internal Tool leveraging our ChromaDB, those should be correctly cited 
  * Code \& Documentation citations 
* Only files that end up being relevant should be included in the final output 









###### **Ingestion Job Schedules** 



* **Nightly Jobs** 

  * The idea here is just that if we end up leveraging anything like Chroma DB to help facilitate answer's the user's question, it will likely be completely dependent on the last time that Ingested Data for that particular Data Source
  * I think that the easiest way to go about handling something like this would be to go through and just set up a nightly job that will fire off an Ingestion Job per Data Source (given that they run async, we would just need to have some indication from DB as to the state of these)
  * There may be a nice way to do this in a Pythonic way as well since we well, so something to at least look into 
* **Web Hooks** 

  * Even with the nightly jobs running, if a user happens to merge some "ground-breaking" code, that data that we have in Chroma will likely be "out-of-date"
  * We can go through and incorporate some Webhooks or something like that with our Data Sources to kick off "re-ingestion" 
  * This seems like non-MVP, but something that would be super cool to do. Example being that you "Publish" updates in Confluence, this sends trigger to our application running, which then subsequently "re-Ingests" the Data Source, ensuring its up to date
  * Similar vein, when you merge to **main,** then we would kick off reingestion make sure the code we have is up to date 







##### Next Steps (Prioritized \& Broken Down)

