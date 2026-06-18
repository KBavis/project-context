# Ingesting Project Specific Changes:


### Conditions To Perform Ingestion
1. Data Source is of type `REPOSITORY`
2. Data Source has `scoped_by_issues` set to True


### Model Updates 

`project_repository_changes` entity (1:1 with `project_data` via composite PK `project_id` + `data_source_id`)
    - FK to `ingestion_job` (indicates time last updated)
    - same composite key as `project_data` (one row per Project ↔ repository DataSource link)
    - list of commits (commit hashes that this Project has)
    - complete project diff ? --> only include if this is easy to do (long term would be nice to see diffs in UI)
    - files modified ? 


### Flow 

1. If data source we're running ingestion job meets condition, invoke this flow 
2. Retrieve any `project_data` records associated with this Data Source 
3. For each `project_data` record, retrieve (if any) the latest state of `project_repository_changes`
        - validate the `project` has an associated `IssueTrackingDataProvider` (exactly one) --> if not, error out! 
        - determine the last time `project_repository_changes` was synced via associated `IngestionJob`, call this `last_sync_time`
        - retreive the `issue_numbers` associated to this `project`
                --> using the assocaited `IssueTrackingDataProvider`, call `get_issues` with the list of `issue_numbers`
                --> for something like `Jira`, this is where we would retrieve the associated `story numbers` tied to the `epics` we provided
                --> for other ones, it could be as simple as just returning the set ones 
                --> we want to do this each time as their could be new `issue_numbers` tied to project, and more stories tied to those issue numbers
                --> output of this step is `task_issue_numbers`
        - leverage the `data_providers` API to find all commits since `last_sync_time` that have `commit messages` that contain any of the `task_issue_numbers`
                --> if there was no associated `project_repository_changes` record, this will retrieve all commits tied to the `Project` for this particular `DataSource`
                --> if there was an existing `project_repository_changes` record, this will just retrieve the latest commit hashes since `last_sync_time`
        - invoke `create_composition_diff` logic 
                --> combine all the diffs and get a diff to see exact project changes 
        - invoke necessary logic to store this in `ChromaDB` and maybe `DocStore`
                --> TODO: Think through how we want to persist this data and have it be accesssible to Agent  
        - update `project_repository_changes` and `file_diff` rows as needed



### Create Composition Diff 

1. Git Cherry Pick Method
    - temporary clone repository (this will done a singular time for a particular ingestion job, not for each `project_data` record)
    - create temporary branch using Project information and ingestion job information
    - using commit hashes that corresponidng to project changes, run `git cherry-pick` on each commit 
    - run `git diff` against the state of our branch and latest version 
    - consume that output of gitt diff, and store 

        
