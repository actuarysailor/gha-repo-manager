from typing import Any
from actions_toolkit import core as actions_toolkit
from tabulate import tabulate

MISSING_SUB_KEY = {
    "files": "branch",
    "labels": "label",
    "branch_protections": "ruleset",
    "variables": "variable",
    "environments": "environment",
}

SUBKEY_HEADER_SYNTAX = {
    # "branch": "Branch <key>",
    # "label": "Updated Label <key>",
    # "environment": "Environment <key>",
}

KEY_TO_CATEGORY = {}

KEY_CHILD_NAME = {
    # "settings": "Setting",
    "labels": "Label",
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
    "settings": "Setting",
    "label": "Setting",
    "ruleset": "Setting",
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

KEYS_TO_DATAFRAME = ["branch_policies", "secrets", "branch", "updated"]

KEYS_TO_COMPARE_A2E = ["settings", "label", "ruleset"]

KEYS_TO_SKIP_A_LEVEL = ["environments", "labels", "branch_protections", "variables"]

KEYS_TO_TREAT_AS_LIST = ["created", "deleted"]


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
    return max([__depth__(v) for v in input_dict.values()])


def __minimum_depth__(input_dict: dict) -> int:
    return min([__depth__(v) for v in input_dict.values()])


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
            result = __dict_embed_key_in_subdict__(dfDict, keyColName, valColName)
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


def __dict_embed_key_in_subdict__(
    input_dict: dict | list, keyColName: str = None, valColName: str = None
) -> list[dict]:
    rows: list[dict] = []
    dfDict = {}
    for k, v in input_dict.items():
        if k.lower() in ACTION_TAKEN.keys():
            _keyColName = COLUMN_VALUE_TO_NAME.get(k, k).capitalize()
            _keyColValue = ACTION_TAKEN.get(k, k).capitalize()
            if isinstance(v, list):
                dfDict[_keyColName] = [_keyColValue] * len(v)
                dfDict[valColName] = v
            elif isinstance(v, dict):
                r = __dict_embed_key_in_subdict__(v, keyColName, valColName)
                rows.extend(r)
            else:
                raise NotImplementedError(f"Unhandled case for {k} in {input_dict}")
        elif keyColName == "Setting":
            v[keyColName] = [k] if isinstance(next(iter(v.values())), list) else k
            rows.extend(__dict_diff_to_columns__(v, None, None))
        else:
            raise NotImplementedError(f"Unhandled case for {k} in {input_dict}")

    return rows


def __dict_diff_to_columns__(input_dict: dict | list, keyColName: str = None, valColName: str = None) -> list[dict]:
    """Maps the typical expected, found difference columns to the appropriate column names and values."""
    dfDict = {}
    expectedLength = __maximum_depth__(input_dict)
    for k, v in input_dict.items():
        if isinstance(v, list):
            if len(v) < expectedLength:
                v = v + [None] * (expectedLength - len(v))
            dfDict[COLUMN_RENAME_MAP.get(k, k).capitalize()] = v
            if OPPOSSING_COLUMN_MAP.get(k, None) is not None:
                dfDict[OPPOSSING_COLUMN_MAP[k]] = [None] * expectedLength
        elif isinstance(v, dict):
            raise NotImplementedError(f"Unhandled case for {k} in {input_dict}")
            # if __maximum_depth__(v) == 1:
            #     for k1, v1 in v.items():
            # else:
            #     dfDict = __dict_to_dfDict__(v, keyColName, valColName)
        else:
            _keyColName = COLUMN_RENAME_MAP.get(k, k).capitalize()
            # _valColName = COLUMN_RENAME_MAP.get(k, k).capitalize()
            if _keyColName not in dfDict.keys():
                dfDict[_keyColName] = []
            dfDict[_keyColName].extend([v])

    if not dfDict:
        return []
    keys = list(dfDict.keys())
    return [dict(zip(keys, vals)) for vals in zip(*[dfDict[k] for k in keys])]


def __dict_to_dfDict__(
    input_dict: dict | list, keyColName: str = None, valColName: str = None
) -> dict:  # should this just return a dataframe?
    if isinstance(input_dict, list):
        col = keyColName or "value"
        return {col: input_dict}
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
            if __maximum_depth__(value) == 0 or (
                __minimum_depth__(value) == 1 and len(set(ACTION_TAKEN.keys()).intersection(value.keys())) > 0
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
                    if k not in result:
                        result[k] = []
                    result[k].extend(v)
        else:
            raise NotImplementedError(f"Unhandled case for {key} in {input_dict}")

    return result


def __list_handler__(value: dict | list) -> str:
    if isinstance(value, list):
        return "\n".join([f"- {v}" for v in value])
    elif isinstance(value, dict):
        return "\n".join([f"- {k}: {v}\n" for k, v in value.items()])


def __summarize_complex_diff__(expected: Any, found: Any, max_len: int = 80) -> str:
    """Summarize complex nested structures (lists, dicts) into readable diffs."""
    exp_str = str(expected)
    found_str = str(found)

    # If both are simple strings/primitives, show direct comparison
    if not isinstance(expected, (dict, list)) and not isinstance(found, (dict, list)):
        return f"{exp_str[:max_len]} → {found_str[:max_len]}"

    # For complex structures, extract key differences
    lines = []

    # If they're the same overall structure, show what changed
    if isinstance(expected, list) and isinstance(found, list):
        if len(expected) != len(found):
            lines.append(f"Length: {len(expected)} → {len(found)}")
        # For lists of dicts, show item-level differences
        if expected and found and isinstance(expected[0], dict) and isinstance(found[0], dict):
            for i, (exp_item, found_item) in enumerate(zip(expected, found)):
                if exp_item != found_item:
                    for k in set(list(exp_item.keys()) + list(found_item.keys())):
                        exp_val = exp_item.get(k)
                        found_val = found_item.get(k)
                        if exp_val != found_val:
                            # For nested dicts, only show the changed keys
                            if isinstance(exp_val, dict) and isinstance(found_val, dict):
                                changed_keys = []
                                for key in set(list(exp_val.keys()) + list(found_val.keys())):
                                    if exp_val.get(key) != found_val.get(key):
                                        changed_keys.append(key)
                                if changed_keys:
                                    lines.append(f"  [{i}] {k}: added/changed keys: {', '.join(changed_keys)}")
                            else:
                                exp_summary = str(exp_val)[:30] if not isinstance(exp_val, (dict, list)) else f"[{type(exp_val).__name__}]"
                                found_summary = str(found_val)[:30] if not isinstance(found_val, (dict, list)) else f"[{type(found_val).__name__}]"
                                lines.append(f"  [{i}] {k}: {exp_summary} → {found_summary}")

    elif isinstance(expected, dict) and isinstance(found, dict):
        all_keys = set(list(expected.keys()) + list(found.keys()))
        for k in sorted(all_keys):
            exp_val = expected.get(k)
            found_val = found.get(k)
            if exp_val != found_val:
                # For nested dicts, show changed keys instead of full content
                if isinstance(exp_val, dict) and isinstance(found_val, dict):
                    changed_keys = []
                    for key in set(list(exp_val.keys()) + list(found_val.keys())):
                        if exp_val.get(key) != found_val.get(key):
                            changed_keys.append(key)
                    if changed_keys:
                        lines.append(f"  {k}: added/changed keys: {', '.join(changed_keys)}")
                else:
                    # Only show if not too large
                    exp_summary = str(exp_val)[:40] if not isinstance(exp_val, (dict, list)) else f"[{type(exp_val).__name__}]"
                    found_summary = str(found_val)[:40] if not isinstance(found_val, (dict, list)) else f"[{type(found_val).__name__}]"
                    lines.append(f"  {k}: {exp_summary} → {found_summary}")

    # Fallback: just show the length difference if it's still too verbose
    if not lines:
        return f"[{type(expected).__name__} len={len(expected) if isinstance(expected, (list, dict)) else '?'}] → [{type(found).__name__} len={len(found) if isinstance(found, (list, dict)) else '?'}]"

    return "\n".join(lines) if lines else "No visible differences"


def __smart_diff_formatter__(value: dict, key_name: str = None) -> str:
    """
    Generalized handler that detects structure patterns and formats accordingly.
    Handles: action diffs (missing/extra/diff), comparison diffs (Expected/Found), and nested structures.
    """

    # Pattern 1: Comparison structure with expected/found at this level
    if "expected" in value or "found" in value:
        expected = value.get("expected")
        found = value.get("found")
        # For complex nested structures, use special summarizer
        if isinstance(expected, (dict, list)) or isinstance(found, (dict, list)):
            summary = __summarize_complex_diff__(expected, found)
            # If summary has newlines, it's a detailed breakdown
            if "\n" in summary:
                return summary
            return summary
        else:
            exp = str(expected)[:50]
            found_str = str(found)[:50]
            return f"Expected: `{exp}` → Found: `{found_str}`"

    # Special handling for "files" key: branch structure with diff/missing/extra
    if key_name == "file" and all(isinstance(v, dict) for v in value.values()):
        lines = []
        for branch_name, branch_data in value.items():
            if isinstance(branch_data, dict):
                lines.append(f"**Branch: {branch_name}**")
                if "missing" in branch_data and branch_data["missing"]:
                    lines.append(f"- Created: {', '.join(branch_data['missing'])}")
                if "extra" in branch_data and branch_data["extra"]:
                    lines.append(f"- Deleted: {', '.join(branch_data['extra'])}")
                if "diff" in branch_data and isinstance(branch_data["diff"], dict):
                    diff_items = []
                    for fname, fprops in branch_data["diff"].items():
                        if isinstance(fprops, dict):
                            insertions = fprops.get("insertions", 0)
                            deletions = fprops.get("deletions", 0)
                            change_type = fprops.get("Change_type", "M")
                            diff_items.append(f"{fname} ({change_type}, +{insertions} -{deletions})")
                    if diff_items:
                        lines.append(f"- Modified: {', '.join(diff_items)}")
                lines.append("")
        return "\n".join(lines).strip() if lines else ""

    # Pattern 2: Action structure (missing/extra/diff with nested items)
    action_keys = set(value.keys()).intersection(ACTION_TAKEN.keys())
    if action_keys:
        lines = []

        # Standard action handling for other keys
        for action in sorted(action_keys):
            action_data = value[action]
            action_verb = ACTION_TAKEN.get(action.lower(), action).capitalize()

            # Check if this is tabular data (dict where nested dicts have comparison properties)
            is_comparison_table = (
                isinstance(action_data, dict)
                and all(isinstance(v, dict) for v in action_data.values())
                and all(
                    any(
                        isinstance(nested_val, dict) and any(k in nested_val for k in ["expected", "found"])
                        for nested_val in item.values()
                    )
                    for item in action_data.values()
                )
            )

            if is_comparison_table:
                # Format as comparison table
                rows = []
                for item_name, item_data in action_data.items():
                    row = {key_name or "Item": item_name}
                    for prop_name, prop_value in item_data.items():
                        if isinstance(prop_value, dict) and any(k in prop_value for k in ["expected", "found"]):
                            exp = str(prop_value.get("expected", ""))[:15]
                            found = str(prop_value.get("found", ""))[:15]
                            if exp != found:
                                row[f"{prop_name}"] = f"{exp} → {found}"
                    rows.append(row)
                lines.append(tabulate(rows, headers="keys", tablefmt="pipe"))
                lines.append("")

            # Sub-pattern 2a: Grouped by type (e.g., Teams/Users)
            elif isinstance(action_data, dict) and all(isinstance(v, (list, dict)) for v in action_data.values()):
                for group_name, group_items in action_data.items():
                    if isinstance(group_items, list) and group_items:
                        lines.append(f"**{action_verb} {group_name}:**")
                        lines.extend([f"- {item}" for item in group_items])
                    elif isinstance(group_items, dict) and group_items:
                        lines.append(f"**{action_verb} {group_name}:**")
                        for item_key, item_value in group_items.items():
                            lines.append(f"- {item_key} ({item_value})")

            # Sub-pattern 2b: Direct list
            elif isinstance(action_data, list) and action_data:
                lines.append(f"**{action_verb}:**")
                lines.extend([f"- {item}" for item in action_data])

            # Sub-pattern 2c: Dict of objects
            elif isinstance(action_data, dict) and action_data:
                for item_name, item_props in action_data.items():
                    if isinstance(item_props, dict):
                        formatted = __smart_diff_formatter__(item_props, item_name)
                        lines.append(f"- {item_name}: {formatted}")

            lines.append("")
        return "\n".join(lines).strip() if lines else ""

    # Pattern 3: Table structure (dict of items, each with consistent properties)
    # Detect if this looks like tabular data: all values are dicts with same key patterns
    all_dicts = all(isinstance(v, dict) for v in value.values())
    if all_dicts and value:
        # Check if all nested dicts have expected/found (comparison table)
        has_comparisons = all(any(k in v for k in ["expected", "found"]) for v in value.values())
        if has_comparisons:
            rows = []
            for item_name, item_data in value.items():
                row = {key_name or "Item": item_name}
                for prop_name, prop_value in item_data.items():
                    if isinstance(prop_value, dict):
                        exp = str(prop_value.get("expected", ""))[:15]
                        found = str(prop_value.get("found", ""))[:15]
                        if exp != found:
                            row[f"{prop_name}"] = f"{exp} → {found}"
                rows.append(row)
            return tabulate(rows, headers="keys", tablefmt="pipe")

        # Otherwise, nested structure needing recursive handling
        lines = []
        for item_name, item_data in value.items():
            lines.append(f"**{item_name}:**")
            for prop_name, prop_value in item_data.items():
                if isinstance(prop_value, dict):
                    formatted = __smart_diff_formatter__(prop_value, prop_name)
                    lines.append(f"- {prop_name}: {formatted}")
                else:
                    lines.append(f"- {prop_name}: {prop_value}")
            lines.append("")
        return "\n".join(lines).strip()

    # Fallback: Simple list formatting
    if isinstance(value, list) and value:
        return __list_handler__(value)

    # Last resort
    return str(value)


def __action_handler__(key: str, value: Any, hdrDepth: str = "#", header: str = None) -> str:
    actionVerb = ACTION_TAKEN.get(key, key).lower()
    header_label = header.capitalize() if header is not None else key.capitalize()
    if isinstance(value, list):
        return f"\n{__section_handler__(actionVerb, value, hdrDepth, f'{actionVerb.capitalize()} {header_label}')}"
    elif isinstance(value, dict):
        key = MISSING_SUB_KEY[header] if header in MISSING_SUB_KEY else key
        headerSyntax = f"{SUBKEY_HEADER_SYNTAX.get(key, key.capitalize() + ' <key>')}: {actionVerb.capitalize()}"
        return "\n".join(
            [__section_handler__(k, v, f"{hdrDepth}", headerSyntax.replace("<key>", k)) for k, v in value.items()]
        )
    else:
        return str(value)


def __key_handler__(key: str, value: Any, hdrDepth: str = "#", header: str = None) -> str:
    # Special handling for rulesets with complex nested structures
    if key in ["org_rulesets", "rulesets"] and isinstance(value, dict) and "diff" in value:
        lines = []
        for ruleset_name, ruleset_diffs in value["diff"].items():
            lines.append(f"**{ruleset_name}:**")
            for prop_name, prop_diff in ruleset_diffs.items():
                if prop_name == "_id":
                    continue
                if isinstance(prop_diff, dict) and "expected" in prop_diff:
                    summary = __summarize_complex_diff__(prop_diff["expected"], prop_diff["found"])
                    if "\n" in summary:
                        lines.append(f"- {prop_name}:")
                        for line in summary.split("\n"):
                            lines.append(f"  {line}")
                    else:
                        lines.append(f"- {prop_name}: {summary}")
            lines.append("")
        return "\n".join(lines).strip()

    if key in ["collaborators", "files", "labels", "branch_protections", "environments"]:
        return __smart_diff_formatter__(value, key_name=key.rstrip("s"))
    elif key in KEYS_TO_DATAFRAME:
        dfDict = __dict_to_dfDict__(
            value, keyColName=KEY_CHILD_NAME.get(key, None), valColName=VAL_CHILD_NAME.get(key, None)
        )
        keys = list(dfDict.keys())
        rows = [dict(zip(keys, vals)) for vals in zip(*[dfDict[k] for k in keys])]
        return tabulate(rows, headers="keys", tablefmt="pipe")
    elif key in KEYS_TO_COMPARE_A2E:
        rows = __dict_embed_key_in_subdict__(
            value, keyColName=COLUMN_RENAME_MAP.get(key, None), valColName=KEY_CHILD_NAME.get(key, None)
        )
        return tabulate(rows, headers="keys", tablefmt="pipe")
    elif key in KEYS_TO_SKIP_A_LEVEL:
        if isinstance(value, list):
            return __list_handler__(value)
        return "\n".join([__key_handler__(k, v, f"{hdrDepth}", key) for k, v in value.items()])
    elif key in ACTION_TAKEN.keys():
        return __action_handler__(key, value, hdrDepth, header)
    elif key in KEYS_TO_TREAT_AS_LIST:
        return __list_handler__(value)
    elif key in MISSING_SUB_KEY.keys():
        key = MISSING_SUB_KEY[key]
        headerSyntax = f"{SUBKEY_HEADER_SYNTAX.get(key, key.capitalize() + ' <key>')}"
        if isinstance(value, list):
            return __list_handler__(value)
        return "\n".join(
            [__section_handler__(k, v, f"{hdrDepth}", headerSyntax.replace("<key>", k)) for k, v in value.items()]
        )
    elif isinstance(value, dict):
        return "\n".join([__section_handler__(k, v, f"{hdrDepth}") for k, v in value.items()])
    else:
        return str(value)


def __section_handler__(
    key: str, value: Any, hdrDepth: str = "#", header: str = None, messages: list[str] = None
) -> str:
    header = KEY_TO_CATEGORY.get(key.lower(), key).capitalize() if header is None else header
    actions_toolkit.debug(f"Generating markdown for differences in {header}")
    body = f"\n{hdrDepth} {header}:\n\n"
    if messages is not None:
        body += "\n".join([f"- {m}\n" for m in messages])
    body += __key_handler__(key, value, f"{hdrDepth}#")
    actions_toolkit.debug(f"Generated markdown for {header}:\n\n{body}")
    return body


def generate(markdown: dict[str, Any], messages: dict[str, list[str]], hdrDepth: str = "#") -> str:
    body = ""
    if messages.get("open", None) is not None:
        body += f"{hdrDepth} {messages['open']}:\n\n"
        hdrDepth += "#"
    for key, value in markdown.items():
        body += __section_handler__(key, value, hdrDepth, messages=messages.get(key, None))
    return body
