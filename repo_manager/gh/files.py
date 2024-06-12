import os
import shutil
import pandas as pd

from pathlib import Path
from typing import Any

from git import Repo, Commit

from actions_toolkit import core as actions_toolkit
from actions_toolkit.file_command import issue_file_command

from github.GithubException import GithubException
from github.Repository import Repository

from repo_manager.schemas.file import BranchFiles, FileConfig
from repo_manager.utils import get_inputs
import re


commitChanges: Commit = None
commitCleanup: Commit = None


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


def __check_files__(repo: Repo, commit_msg: str, files: list[FileConfig]) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
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
    extra = set[str]()
    missing = set[str]()
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
                extra.add(str(fileToDeleteRelativePath))
                actions_toolkit.info(f"Deleted {str(fileToDelete)}")
            else:
                actions_toolkit.warning(
                    f"{str(fileToDeleteRelativePath)} does not exist in {repo.active_branch.name} branch."
                    + "Because this is a delete, not failing run"
                )
        else:
            if file_config.exists and file_config.remote_src and not oldPath.exists():
                raise FileNotFoundError(f"File {file_config.src_file} does not exist in target repo") # {repo}
            if file_config.remote_src and file_config.move and newPath.exists():
                raise FileExistsError(f"File {file_config.dest_file} already exists in target repo") # {repo}
            if oldPath == newPath:
                continue  # Nothing to do
            if oldPath.exists():
                if file_config.remote_src and not file_config.move:
                    missing.add(str(file_config.dest_file))
                    shutil.copyfile(oldPath, newPath)
                    actions_toolkit.info(f"Copied {str(oldPath)} to {str(newPath)}")
                else:
                    os.rename(oldPath, newPath)
                    changed[str(file_config.src_file)] = {"renamed": f"to {str(file_config.dest_file)}"}
                    changed[str(file_config.dest_file)] = {"renamed": f"from {str(file_config.src_file)}"}
                    actions_toolkit.info(f"Moved {str(oldPath)} to {str(newPath)}")

    # we commit these changes so that deleted files and renamed files are accounted for
    global commitCleanup
    repo.git.add("-A")
    if repo.index.diff("HEAD") == []:
        commitCleanup = None
        actions_toolkit.debug("No files to delete or move")
    else:
        commitCleanup = repo.index.commit(commitCleanupMsg)

    if len(extra) > 0:
        diffs["extra"] = list(extra)

    if len(missing) > 0:
        diffs["missing"] = list(missing)

    # get the list of files that were re-organized
    if commitCleanup is not None:
        actions_toolkit.info(f"File Change Commit SHA: {commitCleanup.hexsha}")
        for file in commitCleanup.stats.files:
            if str(Path(file)) not in (missing.union(extra).union(changed.keys())):
                raise RuntimeError(f"File {file} has unaccounted changes!{commitCleanup.stats.files[file]}")

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
                missing.add(str(file_config.dest_file))
            shutil.copyfile(srcPath, destPath)
            actions_toolkit.info(f"Copied {str(srcPath)} to {str(destPath)}")

    if len(missing) > 0:
        diffs["missing"] = list(missing)

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
        for file in commitChanges.stats.files:
            if str(Path(file)) not in missing:
                change = commitChanges.stats.files[file]
                changed[str(Path(file))] = change
            elif str(Path(file)) in changed.keys():
                changed.pop(str(Path(file)))

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
            continue

        branch.target_branch = repo.default_branch if branch.target_branch is None else branch.target_branch

        # Checkout the target branch if it exists
        if branch.target_branch != repo.default_branch and branch.target_branch in [b.name for b in repo.get_branches()]:
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
    repo: Repository, files: list[BranchFiles], diffs: tuple[dict[str, list[str] | dict[str, Any]]]
) -> set[str]:
    """Update files in a repository"""
    errors = []
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

    for branch, diff in diffs.items():
        target_branch = f"repomgr/updates-to-{branch}"
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
            body = "## File updates:\n"
            if diff.get("extra", None) is not None:
                body += "### Deleted:"
                body += "\n".join(["- " + item for item in diff["extra"]])
                body += "\n"
            if diff.get("missing", None) is not None:
                body += "### Created:\n"
                body += "\n -".join(["- " + item for item in diff["missing"]])
                body += "\n"
            if diff.get("diff", None) is not None:
                body += "### Updated:\n"
                tbl = {"File": [], "Lines Added": [], "Lines Removed": [], "Comments": []}
                for f, d in diff["diff"].items():
                    tbl["File"].append(f)
                    tbl["Lines Added"].append(d.get("insertions", None))
                    tbl["Lines Removed"].append(d.get("deletions", None))
                    comments = ""
                    for k, v in d.items():
                        if k not in ["insertions", "deletions", "lines"]:
                            comments += f"- {k}: {v}\n"
                    tbl["Comments"].append(comments)
                body += pd.DataFrame(tbl).to_markdown()
                body += "\n"
            pr = repo.create_pull(title=prTitle, body=body, head=target_branch, base=branch)
            
            body = f"# [{prTitle}]({pr.comments_url})\n\n" + body
            issue_file_command("STEP_SUMMARY", body)
            actions_toolkit.info(f"Created pull request for branch {repo_dir.active_branch.name} to {target_branch}")

    return errors
