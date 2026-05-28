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
    src_file: OptPath = Field(
        None,
        description="Source file to copy from. Can be a local file path, or if you prefix with remote://, "
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

    @field_validator("src_file", mode="before")
    @classmethod
    def validate_src_file(cls, v, info: ValidationInfo) -> Optional[Path]:
        if v is None and info.data.get("exists", True) is not False:
            raise ValueError("Missing src_file")
        if v is None:
            return None
        v = str(v)
        if v.startswith("remote:"):
            info.data["remote_src"] = True
            v = v.replace("remote://", "")
        return Path(v)

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        if self.move is True and self.dest_file is None:
            raise ValueError("Move requires dest_file to be set")
        if self.exists is False and self.src_file is None and self.dest_file is None:
            raise ValueError("dest_file is required when exists is false and src_file is omitted")
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


class BranchFiles(BaseModel):
    # Commit messages and target branches should be set for the set of files, not individually
    commit_msg: str = Field(
        "chore: Updates from repo_manager",
        description="Commit message to commit the file(s) with.",
    )
    target_branch: OptStr = Field(
        None,
        description="Target branch to commit this file to. Default(None) "
        + "means to lookup the default branch of the repo",
    )
    skip: bool = Field(
        False,
        description="If true, this set of files will be skipped. Useful for conditional file copying",
    )
    files: list[FileConfig] = Field(
        [],
        description="List of files to copy. If the file exists in the target_repo, it will be overwritten",
    )
