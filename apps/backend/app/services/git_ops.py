from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import tempfile
from pathlib import Path

from app.pydantic.file_diff_result import FileDiffResult

logger = logging.getLogger(__name__)


# Cap per-file unified diffs at 512 KB to prevent runaway storage / embed costs.
MAX_DIFF_BYTES = 512 * 1024


class GitOperationsService:
    """
    Performs *ephemeral* local git operations to derive the composite diff that
    a set of commits introduced to a specific repository, isolated from all
    other interleaved commits that landed on the same branch.

    Lifecycle
    ---------
    Each call to ``build_composite_diffs`` is fully self-contained:
      1. Blobless shallow-clone of the repository into a throwaway tmp dir.
      2. Create a temp branch rooted at the parent of the earliest project commit.
      3. Cherry-pick each project commit in chronological order, with escalating
         conflict-resolution fallbacks.
      4. Capture ``git diff <base>..tip`` for every touched file.
      5. Destroy the tmp dir unconditionally.

    No state is persisted on disk between calls; the clone is never pushed.
    """

    async def build_composite_diffs(
        self,
        clone_url: str,
        commit_shas: list[str],
        base_sha: str | None = None,
    ) -> tuple[list[FileDiffResult], str]:
        """
        Derive the net composite diff for every file touched by the given
        commits, as if those commits were the *only* changes applied to the
        repository.

        Args:
            clone_url:    HTTPS clone URL of the repository (e.g. https://github.com/owner/repo).
            commit_shas:  Commit SHAs in **chronological (ascending) order**.
                          The caller is responsible for ordering — typically the
                          order returned by ``get_all_commits_info``.
            base_sha:     SHA of the commit immediately before the first project
                          commit.  When provided (re-sync), the clone skips
                          resolution and uses it directly.  When ``None``
                          (first sync), the service resolves it as
                          ``first_commit^``.

        Returns:
            A tuple of (file_diff_results, resolved_base_sha).
            ``resolved_base_sha`` is either the passed-in value or the newly
            computed one — the caller should persist it for future syncs.
        """
        if not commit_shas:
            return [], ""

        tmp_dir: Path | None = None
        try:

            # generate randomized directory for repository clone (i.e `/tmp/ctx_gitops_12fdfsdg2e/repo`)
            tmp_dir = Path(tempfile.mkdtemp(prefix="ctx_gitops_"))
            repo_dir = tmp_dir / "repo"

            # TODO: Inject provider-specific auth for private repositories
            # (GitHub PAT, Bitbucket app passwords, GitLab tokens, etc.)
            # Auth strategy should be derived from DataSource.provider, not hardcoded.
            await self._clone(clone_url, repo_dir)

            # compute the base sha (commit prior to first Project commit for this repo) if one doesn't already exist 
            if base_sha is None:
                base_sha = await self._resolve_base_sha(repo_dir, commit_shas[0])

            # create the temp branch ROOTED at the commit prior to any Project contributon
            await self._create_temp_branch(repo_dir, base_sha)

            # cherry pick relevant Project commit SHAs onto the temp branch
            failed_shas = await self._cherry_pick_all(repo_dir, commit_shas)

            # compute the file diffs for the Project commit SHAs
            results = await self._extract_file_diffs(
                repo_dir, base_sha, failed_shas
            )
            return results, base_sha
        
        except Exception as e:
            logger.error(f"Failure deriving the Diff for repository {clone_url} with Commits={commit_shas} and Base={base_sha}: {e}")
            raise e
        finally:
            if tmp_dir and tmp_dir.exists():
                await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)


    async def _clone(self, url: str, dest: Path) -> None:
        """
        Blobless shallow clone.

        --filter=blob:none  — skips file-content blobs; they are fetched
                              on-demand only for files touched by our cherry-picks.
        --depth=500         — limits the commit graph to the 500 most recent
                              commits; enough for cherry-pick ancestry without
                              pulling full repo history.
        --no-single-branch  — ensures all remote refs are available so we can
                              reference any commit SHA that appears on any branch.
        --quiet             — suppresses verbose clone progress output.

        Args:
            url (str): The URL of the repository to clone.
            dest (Path): The path to clone the repository to.
        """
        cmd = [
            "git", "clone",
            "--filter=blob:none",
            "--depth=500",
            "--no-single-branch",
            "--quiet",
            url,
            str(dest),
        ]
        logger.info(f"Cloning repository into {dest}")
        await self._run(cmd, cwd=None)

    # ------------------------------------------------------------------ #
    # Base SHA resolution                                                   #
    # ------------------------------------------------------------------ #

    async def _resolve_base_sha(self, repo_dir: Path, first_commit_sha: str) -> str:
        """
        Return the SHA of the commit *immediately before* the first project
        commit was merged to the main branch (the ^ suffix tells git to get the parent)

        This is the parent of first_commit_sha — the last state of the repo
        before Project X touched anything.  By starting our temp branch here,
        the eventual ``git diff base..tip`` will contain *only* our project's
        net contribution.

        Note: If the first commit has multiple parents (a merge commit), we
        use the first parent (the mainline parent), which is the conventional
        choice.

        Args:
            repo_dir (Path): the path to the repo
            first_commit_sha (str): the SHA of the first commit Project X introduced to the repo
        
        Returns:
            str: the SHA of the base commit (parent of first_commit_sha)
        """

        # ensure the commit object is available (shallow clones may not have it)
        await self._fetch_if_missing(repo_dir, first_commit_sha)

        stdout = await self._run(
            ["git", "rev-parse", f"{first_commit_sha}^"],
            cwd=repo_dir,
        )
        base_sha = stdout.strip()
        logger.debug(f"Resolved base SHA: {base_sha} (parent of {first_commit_sha})")

        # ensure the parent commit object is also available for checkout
        await self._fetch_if_missing(repo_dir, base_sha)

        return base_sha

    async def _fetch_if_missing(self, repo_dir: Path, sha: str) -> None:
        """
        Attempt to fetch a specific SHA if it isn't already present in the
        shallow clone's commit graph (this can happen when --depth=500 isn't enough).

        Checks if the specified SHA is available in local Git object
        datbaase (using `git cat-file -e <hash>`, where -e is for "exists") 
        and then fetches the commit & tree meta data (excludes the actual file contents)

        Args:
            repo_dir (Path): path to the repository
            sha (str): the commit sha to check for
        """
        try:
            await self._run(["git", "cat-file", "-e", sha], cwd=repo_dir)
        except RuntimeError:
            logger.debug(f"SHA {sha} not found locally — fetching from origin")
            await self._run(
                ["git", "fetch", "--filter=blob:none", "--depth=500", "origin", sha],
                cwd=repo_dir,
            )


    async def _create_temp_branch(self, repo_dir: Path, base_sha: str) -> None:
        """
        Create an ephemeral local branch rooted at base_sha. This branch is never 
        actually pushed to origin and is going to be the "state' of the specified 
        repository prior to any Project contribution

        Args:
            repo_dir:   The path to the repository
            base_sha:   The SHA of the commit to checkout (i.e. the base commit)
        """
        await self._run(
            ["git", "checkout", "-b", "ctx-temp-diff", base_sha],
            cwd=repo_dir,
        )
        logger.debug(f"Created temp branch rooted at {base_sha}")


    async def _cherry_pick_all(
        self, repo_dir: Path, commit_shas: list[str]
    ) -> list[str]:
        """
        Cherry-pick each SHA in order.  Returns the list of SHAs that could
        not be applied even after all fallback attempts.

        Escalation ladder per commit
        ----------------------------
        1. ``git cherry-pick -Xignore-space-change -Xignore-whitespace <sha>``
           Handles whitespace-only conflicts without any abort/reapply cycle.

        2. On failure → abort → ``git format-patch -1 <sha> --stdout |
           git apply --3way --ignore-whitespace``
           Uses a three-way merge when the patch context lines don't match
           exactly (e.g. because an interleaved commit from another project
           shifted surrounding lines).  If apply succeeds we manually commit.

        3. On failure → clean working tree → record sha in failed list →
           continue with remaining commits.

        Args:
            repo_dir (Path):  The path to the repository
            commit_shas (list[str]): List of SHAs to cherry-pick

        Returns:
            list[str]: List of SHAs that could not be applied
        """
        failed: list[str] = []

        # iterate through each commit and attempt to cherry pick onto our temp branch
        for sha in commit_shas:
            await self._fetch_if_missing(repo_dir, sha)

            # 1. attempt to cherry pick the commit with whitespace tolerance
            ok = await self._try_cherry_pick(repo_dir, sha)
            if ok:
                logger.debug(f"Cherry-picked {sha} cleanly")
                continue

            # abort the in-progress cherry-pick (handles above failure gracefully)
            await self._run(["git", "cherry-pick", "--abort"], cwd=repo_dir)
            logger.warning(f"Cherry-pick conflict for {sha} — trying 3-way apply fallback")

            # 2. apply patch as 3-way merge
            ok = await self._try_apply_3way(repo_dir, sha)
            if ok:
                logger.debug(f"Applied {sha} via 3-way fallback")
                continue

            # discard any partial apply, record SHA as failed commit (move on to next commit)
            await self._run(["git", "checkout", "-f", "HEAD"], cwd=repo_dir) # resets partial changes
            await self._run(["git", "clean", "-fd"], cwd=repo_dir) # remove untracked files/dirs
            logger.error(
                f"Could not apply {sha} even with 3-way fallback — recording as failed"
            )
            failed.append(sha)

        return failed

    async def _try_cherry_pick(self, repo_dir: Path, sha: str) -> bool:
        """
        Attempt cherry-pick the specified commit onto our
        temporary branch with whitespace-tolerant strategy options.

        Args:
            repo_dir (Path): path to the repository
            sha (str): the commit sha to cherry-pick
        
        Returns:
            bool: True if the cherry-pick was successful, False otherwise
        """
        try:
            await self._run(
                [
                    "git", "cherry-pick",
                    "-Xignore-space-change",
                    "-Xignore-whitespace",
                    sha,
                ],
                cwd=repo_dir,
            )
            return True
        except RuntimeError:
            return False

    async def _try_apply_3way(self, repo_dir: Path, sha: str) -> bool:
        """
        Generate a patch from the commit and apply it with --3way.
        On success, create a manual commit so the working tree stays clean.

        Args:
            repo_dir (Path): path to the repository
            sha (str): the commit sha to apply the patch to

        Returns:
            bool: True if the apply was successful, False otherwise
        """
        try:
            # convert single commit to a patch file (text representation of its diff)
            patch = await self._run(
                ["git", "format-patch", "-1", sha, "--stdout"], # leverage --stdout in order to pipe output to git apply below
                cwd=repo_dir,
            )

            # apply the diff to the working tree (fall back to 3-way merge and ignore whitespace)
            proc = await asyncio.create_subprocess_exec(
                "git", "apply", "--3way", "--ignore-whitespace",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_dir),
            )
            _, stderr = await proc.communicate(input=patch.encode()) # pass in generated patch via standard input

            # account for 3-way merge failure
            if proc.returncode != 0:
                logger.debug(f"3-way apply failed for {sha}: {stderr.decode()[:200]}")
                return False

            # create a manual commit of the applied changes - so that future operations (e.g. git diff) work as expected
            await self._run(
                ["git", "add", "-A"],
                cwd=repo_dir,
            )
            await self._run(
                ["git", "commit", "--allow-empty", "-m", f"ctx: cherry-pick fallback {sha}"], # --allow-empty flag handles cases where the patch applies as a no-op
                cwd=repo_dir,
            )
            return True

        except Exception as exc:
            logger.debug(f"3-way apply raised exception for {sha}: {exc}")
            return False


    async def _extract_file_diffs(
        self,
        repo_dir: Path,
        base_sha: str,
        failed_shas: list[str],
    ) -> list[FileDiffResult]:
        """
        Run ``git diff <base_sha>..HEAD`` and split the output per file.

        Because our temp branch contains *only* project commits (cherry-picked),
        this diff represents the *net* contribution of the project — other
        projects' interleaved commits on main are completely absent.

        Args:
            repo_dir (Path): The path to the repository.
            base_sha (str): The base commit SHA.
            failed_shas (list[str]): A list of failed SHAs.

        Returns:
            list[FileDiffResult]: A list of file diff results.
        """

        try:
            # get the diff b/t base_sha (starting point prior to Project) and the current head (state after all cherry picked commits)
            raw_diff = await self._run(
                ["git", "diff", f"{base_sha}..HEAD"],
                cwd=repo_dir,
            )
        except RuntimeError as exc:
            logger.error(f"git diff failed: {exc}")
            return []

        if not raw_diff.strip():
            logger.info("git diff produced empty output — no net changes")
            return []

        # for each failed sha, get the files it touched (used later to mark conflict metadata)
        files_touched_by_failed = set()
        for sha in failed_shas:
            try:
                files = await self._run(["git", "show", "--name-only", "--format=", sha], cwd=repo_dir)
                files_touched_by_failed.update(files.splitlines())
            except RuntimeError as exc:
                logger.error(f"Failed to get files for failed sha {sha}: {exc}")

        # parse the diff into per-file chunks 
        return self._parse_diff_by_file(raw_diff, failed_shas, files_touched_by_failed)


    def _parse_diff_by_file(
        self,
        raw_diff: str,
        failed_shas: list[str],
        files_touched_by_failed: set[str],
    ) -> list[FileDiffResult]:
        """
        Split a full unified diff into per-file chunks, then build
        ``FileDiffResult`` objects.  Each diff chunk begins with a
        ``diff --git`` header line.

        Args:
            raw_diff (str): The raw diff output from ``git diff``.
            failed_shas (list[str]): A list of failed SHAs.
            files_touched_by_failed (set[str]): A set of files touched by failed SHAs.

        Returns:
            list[FileDiffResult]: A list of file diff results.
        """

        results: list[FileDiffResult] = []
        current_file: str | None = None
        current_lines: list[str] = []

        def _flush():
            """
            Helper function to act as the "save and reset" button
                - as we iterate through the diff, each time we encounter a new "diff --git", it means
                    that we've finished reading the previous file 
            """

            # allow for innter function (_flush) to read & modify variables belonging to outer function
            nonlocal current_file, current_lines
            if current_file is None:
                return

            # join all lines to create unified diff 
            unified = "".join(current_lines)

            # hash the unified diff (and truncate if necessary)
            truncated, unified_final = self._maybe_truncate(unified)

            # hash the diff (TODO: Consider if we need/should run this in seperate worker thread)
            diff_hash = (
                hashlib.sha256(unified_final.encode()).hexdigest()
                if unified_final
                else ""
            )

            # add FileDiffResult to results list
            results.append(
                FileDiffResult(
                    file_path=current_file,
                    unified_diff=unified_final or None,
                    diff_hash=diff_hash,
                    diff_truncated=truncated,
                    # conflict flag is set globally below for files touched by failed SHAs
                    conflict_detected=False,
                    failed_commit_shas=[],
                )
            )

            # reset our current_file and current_lines to blank slate 
            current_file = None
            current_lines = []

        # iterate through outputted diff line by line 
        for line in raw_diff.splitlines(keepends=True):

            # looks for lines with `diff --git a/... b/...` (unviersal header Git uses to declare "starting diff for new file")
            # EX) "diff --git a/src/foot.py b/src/foo.py"
            if line.startswith("diff --git "):
                _flush()

                # extract the file path from the line
                parts = line.split(" b/", 1)
                current_file = parts[1].rstrip("\n") if len(parts) == 2 else line

            else:
                # everything else becomes part of the diff
                current_lines.append(line)

        _flush()

        # mark conflict metadata on results only for files touched by failed SHAs
        if failed_shas:

            # 1. update the files that DID make it into the diff
            existing_paths = {r.file_path for r in results}
            for r in results:
                if r.file_path in files_touched_by_failed:
                    r.conflict_detected = True
                    r.failed_commit_shas = failed_shas
            
            # 2. inject placeholder results for files that were completely omitted 
            # from the net diff because their ONLY modifying commit failed to merge
            missing_paths = files_touched_by_failed - existing_paths
            for path in missing_paths:
                results.append(
                    FileDiffResult(
                        file_path=path,
                        unified_diff=None,
                        diff_hash="",
                        diff_truncated=False,
                        conflict_detected=True,
                        failed_commit_shas=failed_shas
                    )
                )
        
        return results


    def _maybe_truncate(self, unified: str) -> tuple[bool, str]:
        """
        Cap the diff at MAX_DIFF_BYTES to avoid runaway storage costs.
        Returns (was_truncated, final_text). If anything exceeds this 
        MAX_DIFF_BYTES, someone likely accidently commited something huge

        Args:
            unified (str): The raw diff output from ``git diff``.

        Returns:
            tuple[bool, str]: A tuple containing a boolean indicating whether 
                               the diff was truncated and the final text.
        """
        encoded = unified.encode()
        if len(encoded) <= MAX_DIFF_BYTES:
            return False, unified
        truncated = encoded[:MAX_DIFF_BYTES].decode(errors="replace")
        return True, truncated


    async def _run(self, cmd: list[str], cwd: Path | None) -> str:
        """
        Run a git command asynchronously

        Args:
            cmd (list[str]): The command to run.
            cwd (Path | None): The working directory to run the command in.

        Returns:
            str: The stdout of the command.
        
        Raises:
            RuntimeError: If the command fails.
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command {cmd} failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')[:300]}"
            )
        return stdout.decode(errors="replace")