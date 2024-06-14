from typing import Any
from actions_toolkit import core as actions_toolkit
import pandas as pd

MISSING_SUB_KEY = {
    "files": "branch",
}

SUBKEY_HEADER_SYNTAX = {
    "branch": "branch <key>",
}

KEY_TO_CATEGORY = {}

KEY_CHILD_NAME = {
    # "settings": "Setting",
    # "environments": "Environment",
    # "secrets": "Secret",
    "branch": "File",
}

VAL_CHILD_NAME = {
    "secrets": "Secret",
    "branch_policies": "Protected Branch Pattern",
}

COLUMN_VALUE_TO_NAME = {
    "extra": "Change",
    "missing": "Change",
    "diff": "Change",
    "required_reviewers": "Setting",
    "users": "Collaborator Type",
    "teams": "Collaborator Type",
}

COLUMN_RENAME_MAP = {
    "missing": "Expected",
    "extra": "Found",
    "renamed": "Change",
    "insertions": "Lines Added",
    "deletions": "Lines Removed",
    "lines": "Total Lines",
    "users": "Collaborator",
    "teams": "Collaborator",
}

OPPOSSING_COLUMN_MAP = {
    "missing": "Found",
    "extra": "Expected",
}

ACTION_TAKEN = {
    "extra": "Deleted",
    "missing": "Created",
    "diff": "Updated",
}

KEYS_TO_DATAFRAME = ["settings", "collaborators", "branch_policies", "secrets", "branch"]

KEYS_TO_SKIP_A_LEVEL = ["environments"]


def __depth__(v: Any) -> int:
    if isinstance(v, dict):
        return len(v.keys())
    if isinstance(v, list):
        return len(v)
    if isinstance(v, str | int | bool):
        return 0
    else:
        raise NotImplementedError(f"Unhandled case for {v} in {__depth__}")


def __maximum_depth__(input_dict: dict) -> int:
    return 1 + max([__depth__(v) for v in input_dict.values()])


def __minimum_depth__(input_dict: dict) -> int:
    return 1 + min([__depth__(v) for v in input_dict.values()])


def __transform_diffs__(diffs: dict[str, Any], depth: int = 1) -> dict:
    result = {}
    for k, v in diffs.items():
        if COLUMN_RENAME_MAP.get(k, None) is not None:
            if __depth__(v) <= depth:
                result[COLUMN_RENAME_MAP[k]] = v
            else:
                result[COLUMN_RENAME_MAP[k]] = str(v)
        else:
            raise NotImplementedError(f"Unhandled case for {k} in {diffs}")
    return result


def __validate_df_dict__(dfDict: dict) -> bool:
    expectedLength = len(next(iter(dfDict.values())))
    for v in dfDict.values():
        if len(v) != expectedLength:
            return False
    return True


# Should this just output a dataframe?
def __dict_key_to_columns__(key: str, dfDict: dict | list, keyColName: str = None, valColName: str = None) -> dict:
    """Convert a dictionary to a DataFrame compatible dictionary with the keys as columns and the values as rows.
    This assumes that the dictionary provided is already data frame compatible.
    """
    result = {}
    # category = CATEGORY_MAP.get(category.lower(), category)
    _keyColName = (COLUMN_VALUE_TO_NAME[key.lower()] if keyColName is None else keyColName).capitalize()
    _keyValue = ACTION_TAKEN.get(key.lower(), key).capitalize()
    _valColName = COLUMN_RENAME_MAP.get(key.lower(), key) if valColName is None else valColName.capitalize()
    if isinstance(dfDict, list):
        # Note that above we are using the key to get the category column name, not the column name for the key itself
        if (_keyColName or "").lower() == (_valColName or "").lower():
            raise ValueError(f"Key column name {_keyColName} is the same as value column name {_valColName}")
        result[_keyColName] = [_keyValue] * len(dfDict)
        result[_valColName] = dfDict
    elif isinstance(dfDict, dict):
        if set(ACTION_TAKEN.keys()).intersection(dfDict.keys()):
            if not __validate_df_dict__(dfDict):
                raise ValueError(f"Dictionary {dfDict} is not DataFrame compatible!")
            result = __dict_diff_to_columns__(dfDict, keyColName, valColName)
        else:
            for k, v in dfDict.items():
                # iterating through the dictioary means that we are at the next level down
                # keyColName and valColName apply at the level we entered at
                # we should only be here if each key has a single value
                vColName = COLUMN_RENAME_MAP.get(k.lower(), k).capitalize()
                if vColName == "Change":
                    v = f"{k} {v}"
                result[vColName.capitalize()] = list([v])  # this is a list of one element
        if result.get(_keyColName, None) is not None:
            raise ValueError(f"Column {_keyColName} already exists in {result}")
        result[_keyColName] = [_keyValue.capitalize()] * len(next(iter(result.values())))
    else:
        raise NotImplementedError(f"Unhandled case for {key}")

    if not __validate_df_dict__(result):
        raise ValueError(f"Dictionary {result} is not DataFrame compatible!")

    return result


def __dict_diff_to_columns__(input_dict: dict | list, keyColName: str = None, valColName: str = None) -> dict:
    result = {}
    for k, v in input_dict.items():
        if k.lower() in ACTION_TAKEN.keys():
            _keyColName = COLUMN_VALUE_TO_NAME.get(k, k).capitalize()
            _keyColValue = ACTION_TAKEN.get(k, k).capitalize()
            if isinstance(v, list):
                result[_keyColName] = [_keyColValue] * len(v)
                result[COLUMN_RENAME_MAP[k]] = v
                result[OPPOSSING_COLUMN_MAP[k]] = [None] * len(v)
            elif isinstance(v, dict):
                if __maximum_depth__(v) == 1:
                    for k1, v1 in v.items():
                        # what is the logic here?  I would think we only check key
                        v1ColName = (KEY_CHILD_NAME.get(k1.lower(), k1)).capitalize()
                        result[v1ColName] = list([v1])
                else:
                    result = __dict_to_dfDict__(v, keyColName, valColName)
                if result.get(_keyColName, None) is None:  # files sometimes have this accounted for already
                    result[_keyColName] = [_keyColValue]
            else:
                raise NotImplementedError(f"Unhandled case for {k} in {input_dict}")
        else:
            raise NotImplementedError(f"Unhandled case for {k} in {input_dict}")

    return result


def __dict_to_dfDict__(
    input_dict: dict, keyColName: str = None, valColName: str = None
) -> dict:  # should this just return a dataframe?
    result = {}
    # valColName = (COLUMN_RENAME_MAP.get(key.lower(), None) or COLUMN_RENAME_MAP.get(category, key)).capitalize()
    for key, value in input_dict.items():
        if isinstance(value, list):
            if len(result) == 0:
                result = __dict_key_to_columns__(key, value, keyColName, valColName)
            else:
                _keyColName = (COLUMN_VALUE_TO_NAME[key.lower()] if keyColName is None else keyColName).capitalize()
                _keyValue = ACTION_TAKEN.get(key.lower(), key).capitalize()
                _valColName = COLUMN_RENAME_MAP.get(key.lower(), key) if valColName is None else valColName.capitalize()
                # Note that above we are using the key to get the category column name, not the column name for the key itself
                if _keyColName.lower() == _valColName.lower():
                    raise ValueError(f"Key column name {keyColName} is the same as value column name {valColName}")
                result[_keyColName].extend([_keyValue] * len(value))
                result[_valColName].extend(value)
        elif isinstance(value, dict):
            if __maximum_depth__(value) == 1 or (
                __minimum_depth__(value) == 2 and len(set(ACTION_TAKEN.keys()).intersection(value.keys())) > 0
            ):
                dfDict = __dict_key_to_columns__(key, value, keyColName, valColName)  # used to have category
            else:
                dfDict = __dict_to_dfDict__(value, keyColName, valColName)
                _keyColName = COLUMN_VALUE_TO_NAME.get(key.lower(), None)
                if _keyColName is not None and _keyColName not in dfDict.keys():
                    _keyValue = ACTION_TAKEN.get(key.lower(), key).capitalize()
                    dfDict[_keyColName] = [_keyValue] * len(next(iter(dfDict.values())))
            if len(result) == 0:
                result = dfDict
            else:
                for k, v in dfDict.items():
                    result[k].extend(v)
        else:
            raise NotImplementedError(f"Unhandled case for {key} in {input_dict}")

    return result


def __key_handler__(key: str, value: Any, hdrDepth: str = "#") -> str:
    if key in KEYS_TO_DATAFRAME:
        return pd.DataFrame(
            __dict_to_dfDict__(
                value, keyColName=KEY_CHILD_NAME.get(key, None), valColName=VAL_CHILD_NAME.get(key, None)
            )
        ).to_markdown()  # used to have key?
    elif key in KEYS_TO_SKIP_A_LEVEL:
        return "\n".join([__key_handler__(k, v, f"{hdrDepth}#") for k, v in value.items()])
    elif key in ACTION_TAKEN.keys():
        actionVerb = ACTION_TAKEN.get(key, key).capitalize()
        return "\n".join([__section_handler__(f"{actionVerb} {k}", v, f"{hdrDepth}#") for k, v in value.items()])
    elif key in MISSING_SUB_KEY.keys():
        key = MISSING_SUB_KEY[key]
        headerSyntax = SUBKEY_HEADER_SYNTAX[key]
        return "\n".join(
            [__section_handler__(key, v, f"{hdrDepth}#", headerSyntax.replace("<key>", k)) for k, v in value.items()]
        )
    else:
        return "\n".join([__section_handler__(k, v, f"{hdrDepth}#") for k, v in value.items()])


def __section_handler__(key: str, value: Any, hdrDepth: str = "#", header: str = None) -> str:
    header = KEY_TO_CATEGORY.get(key.lower(), key).capitalize() if header is None else header
    actions_toolkit.debug(f"Generating markdown for differences in {header}")
    body = f"{hdrDepth} {header}:\n\n"
    body += __key_handler__(key, value, f"{hdrDepth}#")
    actions_toolkit.debug(f"Generated markdown for {header}:\n\n{body}")
    return body


def generate(markdown: dict[str, Any], hdrDepth: str = "#") -> str:
    body = ""
    for key, value in markdown.items():
        body += __section_handler__(key, value, hdrDepth)
    return body
