import os
import shutil
from pathlib import Path
from typing import Any

from git import Repo, Commit

from actions_toolkit import core as actions_toolkit
from github.GithubException import UnknownObjectException
from github.Repository import Repository

from repo_manager.schemas import FileConfig
from repo_manager.utils import get_inputs


class RemoteSrcNotFoundError(Exception): ...

commitChanges: Commit = None
commitCleanup: Commit = None

def __clone_repo__(repo: Repository, branch: str) -> Repo:
    """Clone a repository to the local filesystem"""
    inputs = get_inputs()
    repo_dir = Path(inputs["workspace_path"]) / repo.name
    if repo_dir.is_dir():
        raise FileExistsError(f"Directory {repo_dir} already exists")
    cloned_repo = Repo.clone_from(repo.clone_url, str(repo_dir))
    cloned_repo.git.checkout(branch)
    return cloned_repo





def check_files(repo: Repository, files: list[FileConfig]) -> tuple[bool, dict[str, list[str] | dict[str, Any]]]:
    """Check files in a repository"""

    # if no files are provided, return True
    if files is None:
        return True, None
    
    inputs = get_inputs()
    target_branch = files[0].target_branch if files[0].target_branch is not None else repo.default_branch
    
    if inputs["repo"] == "self":
        repo_dir = Repo.init(".")
    else:
        # clone the repo
        repo_dir = __clone_repo__(repo, target_branch)
    
    diffs = {}
    extra = set[str]()
    missing = set[str]()
    moved = set[str]()
    changed = set[str]()

    # First we handle file movement and removal
    for file_config in files:
        if target_branch != (files[0].target_branch if files[0].target_branch is not None else repo.default_branch):
            raise ValueError("All files must have the same target_branch")
        oldPath = Path(repo_dir.working_tree_dir) / file_config.src_file
        newPath = Path(repo_dir.working_tree_dir) / file_config.dest_file
        if not file_config.exists:
            if newPath.exists():
                os.remove(newPath)
                extra.add(str(file_config.dest_file))
            if oldPath.exists():
                os.remove(oldPath)
                if file_config.dest_file not in extra:
                    extra.add(str(file_config.src_file))
        else:
            if not (oldPath.exists() or newPath.exists()):
                missing.add(str(file_config.dest_file))
            if file_config.move:
                if oldPath == newPath:
                    continue # file does not move
                if not oldPath.exists():
                    actions_toolkit.debug(f"File {file_config.src_file} does not exist in {repo}; nothing to move")
                else:
                    os.rename(oldPath, newPath)
                    moved += str(file_config.src_file)
    
    # we commit these changes so that deleted files and renamed files are accounted for
    global commitCleanup
    repo_dir.git.add("-A")
    if repo_dir.index.diff("HEAD") == []:
        commitCleanup = None
        actions_toolkit.debug("No files to delete or move")
    else:
        commitCleanup = repo_dir.index.commit("chore(repo_manager): File cleanup and migration")

    if len(extra) > 0:
        diffs["extra"] = list(extra)

    if len(missing) > 0:
        diffs["missing"] = list(missing)
    
    # now we handle file content changes
    for file_config in files:
        if not file_config.exists:
            continue # we already handled this file
        srcPath = file_config.src_file
        destPath = Path(repo_dir.working_tree_dir) / file_config.dest_file
        if file_config.exists:
            if newPath.exists():
                os.remove(newPath) # Delete the file
            shutil.copyfile(srcPath, destPath)

    # we commit the file updates (e.g. content changes)
    global commitChanges
    repo_dir.git.add("-A")
    if repo_dir.index.diff("HEAD") == []:
        commitChanges = None
        actions_toolkit.debug("No files changed")
    else:
        commitChanges = repo_dir.index.commit("chore(repo_manager): File updates")
    
    # get the list of files that changed content
    if commitChanges is not None:
        for file in commitChanges.stats.files:
            if str(Path(file)) not in missing:
                changed.add(str(Path(file)))

    changed.update(moved)
        
    if len(changed) > 0:
        diffs["diff"] = list(changed)

    if len(diffs) > 0:
        return False, diffs
    
    # Default to no differences
    return True, None

def copy_file(repo: Repository, file_config: FileConfig) -> str:
    """Copy files to a repository using the BLOB API
    Files can be sourced from a local file or a remote repository
    """
    target_branch = file_config.target_branch if file_config.target_branch is not None else repo.default_branch
    try:
        file_contents = (
            file_config.src_file_contents
            if not file_config.remote_src
            else get_remote_file_contents(repo, file_config.src_file, target_branch)
        )
    except UnknownObjectException:
        raise RemoteSrcNotFoundError(f"Remote file {file_config.src_file} not found in {target_branch}")

    try:
        dest_contents = repo.get_contents(str(file_config.dest_file), ref=target_branch)
        result = repo.update_file(
            str(file_config.dest_file.relative_to(".")),
            file_config.commit_msg,
            file_contents,
            sha=dest_contents.sha,
            branch=target_branch,
        )
    except UnknownObjectException:
        # if dest_contents are unknown, this is a new file
        result = repo.create_file(
            str(file_config.dest_file.relative_to(".")), file_config.commit_msg, file_contents, branch=target_branch
        )

    return result["commit"].sha


def get_remote_file_contents(repo: Repository, path: Path, target_branch: str) -> str:
    """Get the contents of a file from a remote repository"""
    contents = repo.get_contents(str(path.relative_to(".")), ref=target_branch)
    return contents.decoded_content.decode("utf-8")


def move_file(repo: Repository, file_config: FileConfig) -> tuple[str, str]:
    """Move a file from a repository"""
    return copy_file(repo, file_config), delete_file(repo, file_config)


def delete_file(
    repo: Repository,
    file_config: FileConfig,
) -> str:
    """Delete a file from a repository"""
    # if we're doing a delete for a move, delete the src_file rather than the dest_file
    to_delete = file_config.src_file if file_config.move else file_config.dest_file
    target_branch = file_config.target_branch if file_config.target_branch is not None else repo.default_branch
    contents = repo.get_contents(str(to_delete.relative_to(".")), ref=target_branch)
    result = repo.delete_file(contents.path, file_config.commit_msg, contents.sha, branch=target_branch)
    return result["commit"].sha
