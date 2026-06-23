from __future__ import annotations
import base64
import logging
import httpx
from typing import AsyncGenerator

from .base import IssueTrackerDataProvider
from app.core import settings

logger = logging.getLogger(__name__)


class JiraDataProvider(IssueTrackerDataProvider):
    """
    Data provider for interfacing with Jira. As of now, the main functionlity
    this provider is responsible for is resolving all the child stories/tasks
    for a given set of 'Epic' keys. This is something that is fairly unique 
    to Jira, so other IssueTrackerDataProvider implementations may just simply 
    return the set of configured IssueKeys set up on a given Project. 
    """
    def __init__(self, data_source):
        super().__init__(data_source=data_source)


    def _validate_url(self):
        # TODO: Implement URL validation
        pass


    def _get_request_headers(self) -> dict[str, str] | None:
        """
        Build the auth header for Jira.

        - Atlassian Cloud uses Basic auth with `email:api_token` (base64-encoded).
        - Atlassian Server / Data Center uses Personal Access Tokens with
          `Authorization: Bearer <PAT>` and rejects Basic.

        Resolution:
          1. If both `JIRA_EMAIL` and `JIRA_API_TOKEN` are set -> Basic (Cloud).
          2. Else if `JIRA_API_TOKEN` is set -> Bearer (Server/DC PAT).
          3. Otherwise -> None (caller will surface a 401).
        """
        token = settings.JIRA_API_TOKEN
        email = settings.JIRA_EMAIL

        if email and token:
            auth_str = f"{email}:{token}"
            b64_auth_str = base64.b64encode(auth_str.encode()).decode()
            return {"Authorization": f"Basic {b64_auth_str}"}
        if token:
            return {"Authorization": f"Bearer {token}"}
        return None


    async def get_issues(self, parent_issues: list[str]) -> list[str]:
        """
        Resolve the stories linked to a given set of Epic keys via the classic
        "Epic Link" custom field (Jira Server / Data Center & Cloud
        company-managed projects).
        """

        if not parent_issues:
            return []

        base_url = self.url.rstrip("/")
        search_url = f"{base_url}/rest/api/2/search"

        parent_issues_jql = ", ".join(f'"{key}"' for key in parent_issues)
        jql = f'"Epic Link" in ({parent_issues_jql})'

        story_keys: list[str] = []
        seen: set[str] = set()

        async with httpx.AsyncClient() as client:
            try:
                # iterate through async generator that's handling paginated requests to Jira
                async for key in self._paginate_search(client, search_url, jql):
                    if key not in seen:
                        seen.add(key)
                        story_keys.append(key)
            except httpx.HTTPStatusError as exc:
                # extract Jira's error message if available 
                body = exc.response.text[:500] if exc.response is not None else ""
                logger.error(
                    "Jira search failed (status=%s) for jql=%r against %s: %s",
                    exc.response.status_code if exc.response is not None else "?",
                    jql,
                    search_url,
                    body,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected error running Jira search for jql=%r: %s",
                    jql, exc,
                )

        logger.info(
            "Resolved %d stories for %d parent issues %s",
            len(story_keys), len(parent_issues), parent_issues,
        )
        return story_keys


    async def _paginate_search(self, client: httpx.AsyncClient, url: str, jql: str) -> AsyncGenerator[str, None]:
        """
        Paginate through Jira search results for the given JQL query, yielding issue keys.
        """
        payload = {
            "jql": jql,
            "fields": ["key"],
            "maxResults": 100,
            "startAt": 0,
        }

        while True:
            response = await client.post(url, json=payload, headers=self.request_headers)
            response.raise_for_status()

            data = response.json()
            issues = data.get("issues", [])
            for issue in issues:
                key = issue.get("key")
                if key:
                    yield key
            

            # break once we've review all results (or if no results retrieved)
            total = data.get("total", 0)
            received = payload["startAt"] + len(issues)
            if received >= total or not issues:
                return
            payload["startAt"] += payload["maxResults"]


    async def get_linked_pull_requests(
        self,
        story_numbers: list[str],
        repository_owner: str,
        repository_name: str,
    ) -> list[dict]:
        """
        Return the raw pull request objects linked to a set of Jira issues for a
        single repository, sourced from Jira's development-status API
        (``dataType=pullrequest``).

        The RepositoryDataProvider drives pull request retrieval but
        delegates the issue<->pull-request lookup here, so PRs are resolved
        per-issue rather than by enumerating every merged pull request in the
        repository.

        Results are deduped by pull request id and filtered to the target
        repository.
        """
        if not story_numbers:
            return []

        base_url = self.url.rstrip("/")
        repo_path = f"/projects/{repository_owner}/repos/{repository_name}".lower()

        async with httpx.AsyncClient() as client:

            # Step 1. Resolve the `issue_ids` corresponding to provided story numbers
            issue_ids = await self._resolve_issue_ids(client, base_url, story_numbers)
            if not issue_ids:
                return []

            seen: set[str] = set()
            pull_requests: list[dict] = []

            # Step 2. For each `issue_id`, pull linked pull requests from Dev-Status API
            detail_url = f"{base_url}/rest/dev-status/latest/issue/detail"
            for issue_id in issue_ids:
                resp = await client.get(
                    detail_url,
                    params={
                        "issueId": issue_id,
                        "applicationType": "stash",  # Bitbucket Server / DC
                        "dataType": "pullrequest",
                    },
                    headers=self.request_headers,
                )
                resp.raise_for_status()
                data = resp.json()

                for detail in data.get("detail", []):
                    for pr in detail.get("pullRequests", []):
                        # ensure we only include pull requests from target repository
                        if not self._pr_repo_matches(pr, repo_path, repository_name):
                            continue
                        pr_id = pr.get("id")
                        if not pr_id or pr_id in seen:
                            continue
                        seen.add(pr_id)
                        pull_requests.append(pr)

            logger.info(
                "Resolved %d linked pull requests via dev-status for %s/%s across %d issues",
                len(pull_requests), repository_owner, repository_name, len(issue_ids),
            )
            return pull_requests


    async def _resolve_issue_ids(
        self, client: httpx.AsyncClient, base_url: str, story_numbers: list[str]
    ) -> list[str]:
        """
        Resolve story numbers to their numeric ids. The dev-status API is keyed
        by numeric ``issueId``, not by story number. One JQL search resolves the
        whole batch.
        """
        keys_jql = ", ".join(f'"{k}"' for k in story_numbers)
        jql = f"issuekey in ({keys_jql})"
        search_url = f"{base_url}/rest/api/2/search"

        ids: list[str] = []
        start = 0

        # perform paginated requests to Jira until ALL issue_ids are resolved 
        while True:
            resp = await client.post(
                search_url,
                headers=self.request_headers,
                json={"jql": jql, "fields": ["id"], "maxResults": 100, "startAt": start},
            )
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            ids.extend(issue["id"] for issue in issues if issue.get("id"))

            total = data.get("total", 0)
            received = start + len(issues)
            if received >= total or not issues:
                break
            start += 100
        return ids


    def _pr_repo_matches(self, pr: dict, repo_path: str, repository_name: str) -> bool:
        """Whether a dev-status pull request entry belongs to the repo we care about."""
        # dev-status PR objects expose the repo via the PR url and the source /
        # destination branch urls (e.g. .../projects/<proj>/repos/<repo>/...).
        candidate_urls = [
            pr.get("url") or "",
            (pr.get("source") or {}).get("url") or "",
            (pr.get("destination") or {}).get("url") or "",
        ]
        for url in candidate_urls:
            if url and repo_path in url.lower():
                return True
        # Fallback to slug match when the repository is exposed directly.
        repo = pr.get("repository") or {}
        return (repo.get("name") or "").lower() == repository_name.lower()
