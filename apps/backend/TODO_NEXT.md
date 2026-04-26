
## Enhancing The Agentic Pipeline 

1. Orchestrator 
    
    - I think this agent should be the "control" agent that will generally be the center of truth for whole workflow
    - It should be able to diagnose the next steps, and information that it needs 
    - It will be able to hand off to code / docs agent, but I think those should simply be "tasks" that its effectively telling it to do 
    - For example, "The user wants an overview of the project, we should likely investigate the documentation for general understanding of what its about, and maybe peek at general architecutre:
            - The agent then "discovers" potnetial docs files, and based on names, can choose which will be helpful
            - If useful information, make sure we maintain memory of it for synthessi answer
            - Then it does something ismilar for code agent 
    - The agent should also be able to possibly plan accordingly as to what it should be doing 
        - I can see an argument for this being a seperate agent 
        - Such that the flow goes Orchestrator --> Plan Agent --> Docs | Code Agents --> Synth Agent 
            - orchetrator breaks down and understands questions and what not, and data sources it has, yada yada, and then the planning is what we will execute in the wokrlfow 
        - This plan seems like something that would be useful information to show / debug the issues, and I would like to be able to acutally see the plan if possible, I'm not sure if that's only possible 
            from peeking at debug logs to correesponding LLM providers 
        - As of now, it feels like the missing piece of our code is like a "driver" and the "plan", the concept of almost like "brute force searching" seems to be current methodology for answering questions 
        - This seems not very intutive and I would like to enforce that intution a bit 
    - Should be able to analyze question and determine if there is something ins " specific" that the users looking to understand from the project (i.e functionality, file name, function, etc)
        - This should be duly noted so that when we perfomr searching, we can make sure that we're answering the users question 
        - The agent should try and continue going until it's determined its answered users question, or if its determined that it cannot be answered from context gatehred
        - It shouldn't just go on wild goose chase for endless amount of time reading every file, there should almost be like a "grepping" capabilites 
    - Utilization of MCP tooling is a big one. A data source is essentially just a link, and the agent should learn how to use tools
        - we pass actual tools that can be used by agnets to only code and docs agent 
        - the orchestrator just gets a list of tools, and maybe it would make sense for it to determine what tool it should use? or maybe thats code/dcos agent job? 
        - we have a follow on to sort of "restrict" the number of MCP tools that can be leveraged based on users questions, but that's not currently impelemted (mainly to reduce bloat)


2. Code / Docs Agent
    - sort of thinking of having these be more of a "acting" agent
    - not sure if my vision is correct, since more times than not, the MCP servers are the "action" themsevles, and more times than not, it will likely be a multi step process, such as leveraging tool multiple times and then making a deduction as to what was learned and should be passed on for anser 
    - a big thing I think that we can already account for though in these is really the utilization of a particular file in our answer, i.e the CITATIONS 
    - when we find a relevant piece of code, or snippet from a particular piece of documentation that can be used to answer the question, I think it's important that we do so 
    - that way, when the synthesis agent is ran, and its given all details and users questions, and what not, it's able to comprhesinviely explain answer and provide code / docs links so 
        user can fact check this 


3. Synth Agent 
    - I think this agent generally speaking can remain somewhat similar
    - The big thing I think that it will need to be good at is the formatting and inclusion of citations that are passed from preceeding agents 
    - This really is the "response genetaro" that takes user original question, takes the pieces of information that are retireved, understands "thoughts / context" gatehred from preceeding agent, a
        and formats a well put together response to the users question, overall just having everything come togehter 



** Big Issues**
The really big issue is that the agnetic flow gets so lost. Questions that you feel should be simple like "tell me about Ingestion Jobs in the scope of this project" end up getitng burried 
in millions of MCP server calls that have no real purpose. The perfect world in my mind there is that it's able to simply just understand that the real goal of this question is 
        - Okay, I wonder if any documentation on this? --> No Documentation
        - Interesting, okay, lets look at code for this word, almost like "grep" functionality looking for key words super fast (not exact match, but just lookign for it)
        - Awesome, found a service / entity /rotuer for works like this 
        - Lets peek at these files
        - intersting, so they have some endpoints around it that kick of these flows and seems to insert into something 
        - lets peek at what 
        - ah, it inserts into ChromaDB, which is vector DB, so that's seemingly so that they can query this later down the line for quick answering 


Similar sense, the generic questions like "just tell me about this project" shouldn't just result in searching across everything, it should really entail "lets look at every single file", 
it shold take a similar sort of 
    - Okay they want to know about project, that feels like a question answerrable by documetnation
    - Lets check docs that they have in repository (i.e files ending in .md, etc)
    - Ah, they have README.md, let's read through that 
    - Ah, that's what project is about! 
    - They didn't ask the "how", so probably good enough arleady!


FOllowing questions like whats the architecutre like, shoudln't just look at everything, but look at files, get genreal udnerstanding, understand maybe dependnecies used, etc etc 
 Tool Retrieivng Functionality 
- As of now, the k


IMPORTANT CAVEAT: I think a big reason behind this not being as good as I want it to be really is 


## Integration of Our Internal Tooling 

1. Our Ingestion capabilities allows for the ability to read through PDFS 
2. This seems like something fairly necessary for someone that manually needs to add Documentation to query from 
3. For example, we could have someone who creates new "Manual Data Source", and then the files associated to that Data Source need to be manually added by User (i.e if its blocked site)
4. When a query comes thorugh, we may want to peek at the contents of PDFs, which is where this tooling comes into play 

**IDEA** 
The inital searching of these files can likely help point to WHERE to start searching for a particular file 
For example, we query for the word X and then see all instance of this word 
Maybe good for speciifc situations (not so good for general gist questions)
Idea of ingesting still makes sense? 

**Long Term Solution** 
Web hooks that when we update a data source that we are watching (such as GitHub, BitBucket, Confluence), that this will automatically kick off the ingestion job 
so that its up to date 



## Ability to Add Manual Data Source 

1. House files in AWS S3 
2. Ingest into Chroma DB 
3. Allow for querying of information from those files 


## Utiliation Of Citations 

Adding the enforcement of citations when answering a particular question 
When the code or the docs agent retrieved content that it thinks is going to be useful in answering/supporting their answer, they should "save it" in memory 
When passing to the synth agent, this should formalize the actual citation links that the user should be able to access directly to find where their getting their answer 
This also means we can likely yank this concept from the citation service and what not, depending on if we think that we should leverage a 




## Work Integrations 

1. Ability to search through Confluence Documentation 

2. Jira Integrations (abilitiy to get relevant Story numbers associated with Epics)

3. Ability to deal with retrieivng code snippets and commits and PRs that are only tied to set of Jira Ticket numbers
        - this especially will be useful for larger repositoreis where the "Project" isn't just the whole data source, but rather the functionality added by Proejct 
    
4. General Understanding 
        - along with a Project being scoped to Jira Tickets and what not, there still is value in have that "higher level" architecture understanding 
        - for example, understanding how and what the banks microservice does/did prior the Project, and then what it does now 
        - this means we may need to have some nuance here 