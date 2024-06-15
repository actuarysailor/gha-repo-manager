
import sys
import os
import shutil

from pathlib import Path
from typing import Any

from git import Repo, Commit
from git.types import Files_TD

from actions_toolkit import core as actions_toolkit

from github.GithubException import GithubException
from github.Repository import Repository

from repo_manager.schemas.file import BranchFiles, FileConfig
from repo_manager.utils import get_inputs
from repo_manager.utils.markdown import generate
import re


commitChanges: Commit = None
commitCleanup: Commit = None


def __aggregate_renamed_git_diff__(pathMap: dict[str, str], diff: dict[str, Files_TD]) -> dict[str, Files_TD]:
    """Get the file differences -- this is used to handle file moves and renames"""

    for k in filter(lambda k: k in pathMap.keys(), diff.keys()):
        newPath = pathMap[k]
        for metric in diff[newPath].keys():
            if metric == "deletions":
                diff[newPath][metric] -= diff[k]["insertions"]
            elif metric == "insertions":
                diff[newPath][metric] -= diff[k]["deletions"]
            else:
                diff[newPath][metric] -= diff[k][metric]

    for k in pathMap.keys():
        if k in diff.keys():
            diff.pop(k)

    return diff


def __aggregate_git_diff_multiple_commits__(
    diff: dict[str, Files_TD], commit: dict[str, Files_TD]
) -> dict[str, Files_TD]:
    """Add the file differences"""
    unchangedFiles = [k for k in filter(lambda k: k not in commit.keys(), diff.keys())]
    [diff.pop(k) for k in unchangedFiles]
    for k in diff.keys():
        metrics = commit.pop(k)
        for metric in ["insertions", "deletions", "lines"]:
            if diff[k] is None:
                diff[k] = {"insertions": 0, "deletions": 0, "lines": 0}
            if diff[k].get(metric, None) is None:
                diff[k][metric] = metrics[metric]
            else:
                diff[k][metric] += metrics[metric]
        else:
            diff[k] = metrics

    return diff


def __clone_repo__(repo: Repository, branch: str) -> Repo:
    """Clone a repository to the local filesystem"""

    inputs = get_inputs()
    repo_dir = Path(inputs["workspace_path"]) / repo.name
    if repo_dir.is_dir():
        raise FileExistsError(f"Directory {repo_dir} already exists")
    actions_toolkit.info(f"Cloning {repo.full_name} to {repo_dir}")
    cloned_repo = Repo.clone_from(repo.clone_url.replace("https://", f"https://{inputs['token']}@"), str(repo_dir))
    cloned_repo.git.checkout(branch)
    return cloned_repo


def __check_files__(
    repo: Repo, commit_msg: str, files: list[FileConfig]
) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
    """Check files in a repository"""

    # if no files are provided, return True
    if files is None:
        return True, None

    if re.search(r"\((\w+)\):", commit_msg):
        commitCleanupMsg = re.sub(r"\((\w+)\):", r"(\1-maint):", commit_msg)
        commitUpdateMsg = re.sub(r"\((\w+)\):", r"(\1-update):", commit_msg)
    elif re.search(r"(\w+):", commit_msg):
        commitCleanupMsg = re.sub(r"(\w+):", r"\1(maint):", commit_msg)
        commitUpdateMsg = re.sub(r"(\w+):", r"\1(update):", commit_msg)
    else:
        commitCleanupMsg = f"chore:(maint): {commit_msg}"
        commitUpdateMsg = f"chore:(update): {commit_msg}"

    diffs = {}
    extra = {}
    missing = {}
    changed = {}

    # First we handle file movement and removal
    for file_config in files:
        oldPath = Path(repo.working_tree_dir) / file_config.src_file
        newPath = Path(repo.working_tree_dir) / file_config.dest_file
        # prior method used source if move was true, dest if not
        if not file_config.exists:
            fileToDelete = oldPath if file_config.move else newPath
            fileToDeleteRelativePath = fileToDelete.relative_to(repo.working_tree_dir)
            if fileToDelete.exists():
                os.remove(fileToDelete)
                extra[str(fileToDeleteRelativePath)] = {"insertions": 0, "deletions": 0, "lines": 0}
                actions_toolkit.info(f"Deleted {str(fileToDelete)}")
            else:
                actions_toolkit.warning(
                    f"{str(fileToDeleteRelativePath)} does not exist in {repo.active_branch.name} branch."
                    + "Because this is a delete, not failing run"
                )
        else:
            if file_config.exists and file_config.remote_src and not oldPath.exists():
                raise FileNotFoundError(f"File {file_config.src_file} does not exist in target repo")  # {repo}
            if file_config.remote_src and file_config.move and newPath.exists():
                raise FileExistsError(f"File {file_config.dest_file} already exists in target repo")  # {repo}
            if oldPath == newPath:
                continue  # Nothing to do
            if oldPath.exists():
                if file_config.remote_src and not file_config.move:
                    missing[str(file_config.dest_file)] = {"insertions": 0, "deletions": 0, "lines": 0}
                    shutil.copyfile(oldPath, newPath)
                    actions_toolkit.info(f"Copied {str(oldPath)} to {str(newPath)}")
                else:
                    os.rename(oldPath, newPath)
                    # changed[str(file_config.src_file)] = {"renamed": f"to {str(file_config.dest_file)}"}
                    changed[str(file_config.dest_file)] = {
                        "renamed": f"from {str(file_config.src_file)}",
                        "insertions": 0,
                        "deletions": 0,
                        "lines": 0,
                    }
                    actions_toolkit.info(f"Moved {str(oldPath)} to {str(newPath)}")

    # we commit these changes so that deleted files and renamed files are accounted for
    global commitCleanup
    repo.git.add("-A")
    if repo.index.diff("HEAD") == []:
        commitCleanup = None
        actions_toolkit.debug("No files to delete or move")
    else:
        commitCleanup = repo.index.commit(commitCleanupMsg)

    # get the list of files that were re-organized
    if commitCleanup is not None:
        actions_toolkit.info(f"File Change Commit SHA: {commitCleanup.hexsha}")
        renamedFiles = {
            str(f.src_file): str(f.dest_file) for f in filter(lambda f: str(f.src_file) != str(f.dest_file), files)
        }
        for file in commitCleanup.stats.files:
            if str(Path(file)) not in missing.keys() | extra.keys() | changed.keys() | renamedFiles.keys():
                raise RuntimeError(f"File {file} has unaccounted changes!{commitCleanup.stats.files[file]}")
        commitChgs = {str(f): commitCleanup.stats.files[f] for f in commitCleanup.stats.files}
        aggregated = __aggregate_renamed_git_diff__(renamedFiles, commitChgs)
        [changed.pop(f) for f in filter(lambda f: f in changed.keys(), renamedFiles.keys())]
        for f, d in aggregated.items():
            if str(f) in missing.keys():
                for metric in missing[f].keys():
                    missing[f][metric] = d[metric]
            elif str(f) in extra.keys():
                for metric in extra[f].keys():
                    extra[f][metric] = d[metric]
            if str(f) in changed.keys():
                for metric in d.keys():
                    changed[str(f)][metric] = d[metric]

    # now we handle file content changes
    for file_config in files:
        if not file_config.exists or file_config.remote_src:
            continue  # we already handled this file
        srcPath = file_config.src_file
        destPath = Path(repo.working_tree_dir) / file_config.dest_file
        if file_config.exists:
            if newPath.exists():
                os.remove(newPath)  # Delete the file
            else:
                missing[str(file_config.dest_file)] = {"insertions": 0, "deletions": 0, "lines": 0}
            shutil.copyfile(srcPath, destPath)
            actions_toolkit.info(f"Copied {str(srcPath)} to {str(destPath)}")

    # we commit the file updates (e.g. content changes)
    global commitChanges
    repo.git.add("-A")
    if repo.index.diff("HEAD") == []:
        commitChanges = None
        actions_toolkit.debug("No files changed")
    else:
        commitChanges = repo.index.commit(commitUpdateMsg)

    # get the list of files that changed content
    if commitChanges is not None:
        actions_toolkit.info(f"File Change Commit SHA: {commitChanges.hexsha}")
        commitChgs = {str(f): commitChanges.stats.files[f] for f in commitChanges.stats.files}
        for f, v in commitChgs.items():
            if str(Path(f)) in missing.keys():
                for m, c in v.items():
                    missing[str(Path(f))][m] += c
            elif str(Path(f)) in extra.keys():
                for m, c in v.items():
                    extra[str(Path(f))][m] += c
            elif str(Path(f)) in changed.keys():
                for m, c in v.items():
                    changed[str(Path(f))][m] += c
            else:
                raise RuntimeError(f"File {file} has unaccounted changes!{commitCleanup.stats.files[file]}")

    if len(extra) > 0:
        diffs["extra"] = extra

    if len(missing) > 0:
        diffs["missing"] = missing

    if len(changed) > 0:
        diffs["diff"] = changed

    if len(diffs) > 0:
        return False, diffs

    # Default to no differences
    return True, None


def check_files(repo: Repository, branches: list[BranchFiles]) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
    """Check files in a repository"""

    # if no files are provided, return True
    if branches is None:
        return True, None

    inputs = get_inputs()
    if inputs["repo"] == "self":
        repo_dir = Repo(".")
    else:
        # clone the repo
        repo_dir = __clone_repo__(repo, repo.default_branch)

    diffs = {}
    for branch in branches:
        if branch.skip:
            actions_toolkit.info(f"Skipping file sync to branch {branch.target_branch}")
            continue

        branch.target_branch = repo.default_branch if branch.target_branch is None else branch.target_branch

        # Checkout the target branch if it exists
        if branch.target_branch != repo.default_branch and branch.target_branch in [
            b.name for b in repo.get_branches()
        ]:
            repo_dir.git.checkout(branch.target_branch)

        # Create and checkout a new branch
        new_branch = repo_dir.create_head(f"repomgr/updates-to-{branch.target_branch}")
        new_branch.checkout()

        # Check the files
        success, diff = __check_files__(repo_dir, branch.commit_msg, branch.files)
        if not success:
            diffs[branch.target_branch] = diff

    if len(diffs) > 0:
        return False, diffs

    return True, None


def update_files(
    repo: Repository, branches: list[BranchFiles], diffs: tuple[dict[str, list[str] | dict[str, Any]]]
) -> tuple[set[str], set[str]]:
    """Update files in a repository"""
    errors = []
    messages = []
    if diffs is None:
        return errors
    inputs = get_inputs()

    if inputs["repo"] == "self":
        repo_dir = Repo.init(".")
    else:
        repoPath = Path(inputs["workspace_path"]) / repo.name
        if not repoPath.exists:
            raise FileExistsError(f"Directory {repoPath} does not exist!")
        if not repoPath.is_dir():
            raise NotADirectoryError(f"{repoPath} is not a directory!")
        repo_dir = Repo(repoPath)

    for branch in branches:
        if branch.skip:
            actions_toolkit.info(f"Skipping file sync to branch {branch.target_branch}")
            continue
        if branch.target_branch in set(diffs.keys()):
            diff = diffs[branch.target_branch]
            target_branch = f"repomgr/updates-to-{branch.target_branch}"
            repo_dir.git.checkout(target_branch)
            prTitle = repo_dir.active_branch.commit.message

            origin = repo_dir.remote()
            pushInfo = origin.push(repo_dir.active_branch.name)

            if pushInfo.error is not None:
                for info in pushInfo:
                    if info.ERROR:
                        errors.append(
                            {
                                "type": "file-update",
                                "key": info.local_ref.commit.hexsha,
                                "error": f"{GithubException(info.ERROR, message = info.summary)}",
                            }
                        )
            else:
                actions_toolkit.info(f"Pushed changes to remote {repo.full_name} branch {repo_dir.active_branch.name}")
                body = generate({"files": {branch.target_branch: diff}}, {"files": []})
                # body += f"\n\nCommit SHA: {repo_dir.active_branch.commit.hexsha}"
                body += f"\n\nGenerated by [Repo Manager]({inputs['github_server_url']}/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')})"
                pr = repo.create_pull(title=prTitle, body=body, head=target_branch, base=branch.target_branch)

                # this should occur in the logging of main
                messages.append(f"PR @ {repo.full_name} - [#{pr.number} {prTitle}]({pr.comments_url})\n\n")
                actions_toolkit.info(f"Created pull request for branch {repo_dir.active_branch.name} to {target_branch}")

    dir = Path(repo_dir.working_tree_dir)
    repo_dir.close()
    if dir.exists() and sys.platform != "win32":
        shutil.rmtree(dir)

    return errors, messages
