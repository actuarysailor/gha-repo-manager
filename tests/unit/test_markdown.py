import os

from repo_manager.main import __markdown_summary__


VALID_DIFF = {
    "settings": "private --expected false --found true",
    "collaborators": {
        "missing": ["collaborator1", "collaborator2"],
        "extra": ["collaborator3"],
    },
    "labels": {
        "missing": ["label1", "label2"],
        "extra": ["label3"],
        "diff": {
            "label4": {"name": "Expected label5 found label4"},
            "label6": {"name": "Expected label7 found label6"},
        },
    },
    "branch_protections": {
        "missing": ["branch1", "branch2"],
        "extra": ["branch3"],
        "diff": {
            "branch4": {"name": "Expected branch5 found branch4"},
            "branch6": {"name": "Expected branch7 found branch6"},
        },
    },
    "secrets": {
        "missing": ["secret"],
        "extra": ["secret2"],
    },
    "variables": {
        "missing": ["variable"],
        "extra": ["variable2"],
    },
    "environments": {
        "missing": ["environment"],
        "extra": ["environment2"],
    },
    "files": {
        "missing": ["file"],
        "extra": ["file2"],
    },
}


def test_markdown():
    md = __markdown_summary__(VALID_DIFF)
    os.system(f"echo {md}")
    assert isinstance(md, str)
