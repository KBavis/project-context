# Done So Far 
1. Added new models, "file_diff" and "project_changes"
    - file_diff is the aggregate changes made for a particular file in a data source done as a result of Project 
    - project_repository_changes is the over-arching parent object that relates all repository changes as a result of a Project 
2.Refactored Data Providers 
    - "ingestible" vs "fetchable" data providers 
    - abstracting related groupings of data providers 
    - skipping ingestion on "non-Ingestible" data providers 
3. Ability to create a 'Repository Data Source' that will be scoped by project 


# Required Next Steps 
1. If there is a Data Source created that says 'scoped_by_issues', and someone tries to create a Project linked to this Data Source,
or they try to link the Project to Data Source after the fact, but there are no configured Issue Keys, then we should disallow 
this action, as there will no distingushable way to determine how to split up data source 

2. Figure out how to create composition diff 
    - git cherry pick 
    - merge conflicts 
    - temporary branch that we keep "persisted", when we "re-sync", we're effectively going to just be pulling in some additional commits 
        that we're not previously on our temporary branch 
    - **open questions**
        - do we need to go through and temporary clone each repository into our container (delete after?), check if the project branch exists, if it does exist, we checkout that branch via git commands (or we create the branch, this would need to be some sort
        of unique naming convention (i.e data source ID and project ID, or like a better naming convention)), 
        - can we simply just cherry pick commits without merge conflicts? I think this would work since there since the merge conflicts would have been resolved during merge? 
    - **steps**
        - iterate through each `project` record (or this can _synced_ for a particular project)
        - this flow will be invoked during an `IngestionJob` running for a particular `DataSource`
        - invoke `repository_sync` logic (i.e some service) for the given `data_source` (this should be async) if `scope_by_issues` is set 
        to true and `DataSource` is of type `Repository`
        - `repository_sync` flow (optional argument of `list of projects to run ingestion for`)
            - grab all `projects` assocaited to this `DataSource` 
                --> if none, error out 
                --> only grab the `project`'s specified if one is 
            - iterate through each of the retrieved `projects`
            - grab associated `project_repository_changes` (if one exists) 
            - if one exists:
                    - a) determine the latest commit persisted to `project_repository_changes`
                    - b) grab the assocaited `IssueDataProvider` tied to this `project`
                    - c) if <> 1 **exactly**, error out 
                    - d) from this `IssueDataProvider`, retrieve the `issue_numbers` that are tied for a particular Project 
                            --> get the `project.epics` tied to the current project (probably change this naming convention)
                            --> if none exist, error out 
                            --> call the `get_tickets` for the `IssueDataProvider` with configured ones on `project` 
                    - e) if no `issue_numbers` retrieved, skip remaining sync (since we need this to find commits)
                    - f) using the current `RepositoryDataProvider`, pass the `issue_numbers` to the `get_latest_commit` functionality 
                        setup for the `RepositoryDataProvider` 
                            --> we should go and use the repository provider (i.e GitHub, BitBucket) to get commits with the commit 
                                message including one of our determined `issue_numbers` in the commit message
                            --> if we see no commits, we can skip remaining syncing for this `project` 
                    - g) if the `latest_commit` doesn't match the commit persisted in `project_repository_changes`, we need to invoke our 
                        `resync_logic` for our `DataSource` and our `Project` 
            - `resync_logic` (project_id, data_source_id)
                    - call `get_commit_hashes(last_commit)` 
                            --> this should get all commit hashes since the optional `last_commit` 
                            -->  the `last_commit` would be what we use if we have a `project_repository_changes`, if there 
                                is no `project_repository_changes`, then we pass nothing
                            --> return back `commit_hashes` 
                    - check if the repository is already cloned in the container 
                    - if its not, clone the repository into the container 
                    - check if the branch by the expected naming convention exists 
                    - if not, checkout new branch from the "lastest" version of the branch 
                        --> ensure we pull if it was already tere 
                    - 




3. Restrict any editting or manipulation of a Data Source when the `record_lock` is enabled 