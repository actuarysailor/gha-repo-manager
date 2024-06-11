import os
from pathlib import Path
from typing import Optional, Self

from pydantic import (
    BaseModel,  # pylint: disable=E0611
    ValidationInfo,
    Field,
    field_validator,
    model_validator,
)

OptBool = Optional[bool]
OptStr = Optional[str]
OptPath = Optional[Path]


class FileConfig(BaseModel):
    exists: OptBool = Field(True, description="Set to false to delete dest_file")
    remote_src: OptBool = Field(False, description="If true, src_file is a remote file")
    src_file: Path = Field(
        description="Sourrce file to copy from. Can me a local file path, or if you prefix with remote://, "
        + "a path inside the target_repo. Can be relative to the GHA workspace",
    )
    dest_file: Path = Field(
        None, description="Dest file path in the dest_repo for src_file. Relative to root of the target repo"
    )
    move: OptBool = Field(
        False,
        description="If true and dealing with a remote src_file, repo_manager will move the file instead of "
        + "copying it, by removing src_file after copy. If src_file is a local file, this option is ignored.",
    )
    # Commit messages and target branches should be set for the set of files, not individually
    commit_msg: str = Field(
        "repo_manager file commit",
        description="Commit message to commit the file with. Files with the same commit message "
        + "and target_branch will be commited in one commit.",
    )
    target_branch: OptStr = Field(
        None,
        description="Target branch to commit this file to. Default(None) "
        + "means to lookup the default branch of the repo",
    )

    @field_validator("src_file", mode="before")
    @classmethod
    def validate_src_file(cls, v, info: ValidationInfo) -> Path:
        if v is None and info.data["exists"]:
            raise ValueError("Missing src_file")
        v = str(v)
        if v.startswith("remote:"):
            info.data["remote_src"] = True
            v = v.replace("remote://", "")
        return Path(v)

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        if self.move is True and self.dest_file is None:
            raise ValueError("Move requires dest_file to be set")
        if self.dest_file is None:
            self.dest_file = self.src_file
        return self

    @property
    def src_file_exists(self) -> bool:
        """Checks if local file exists"""
        return os.path.exists(self.src_file) if self.src_file is not None else None

    # Not needed, but still used in tests I have not cleaned up...
    @property
    def src_file_contents(self) -> str:
        """Returns the contents of the local file"""
        if not self.src_file_exists:
            raise ValueError("Local file does not exist")
        with open(self.src_file) as fh:
            return fh.read()

    # Not needed, but still used in tests I have not cleaned up...
    # if we want to set commit messages, it should be done in groups of files, not per file
    @property
    def commit_key(self) -> str:
        """Returns the commit key for this file_config, a combination of commit msg and target_branch"""
        target_branch = self.target_branch if self.target_branch is not None else ""

        return f"{self.commit_msg}_{target_branch}"
