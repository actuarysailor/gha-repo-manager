"""Manage org-level Actions and Dependabot secrets/variables."""

from typing import Any

from actions_toolkit import core as actions_toolkit
from github.Organization import Organization

from repo_manager.schemas.org_settings import OrgSecret, OrgSecretVisibility, SecretEnvError


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _secret_api_base(org: Organization, secret_type: str) -> str:
    """Return the base API path for actions or dependabot org secrets."""
    if secret_type == "dependabot":
        return f"/orgs/{org.login}/dependabot/secrets"
    return f"/orgs/{org.login}/actions/secrets"


def _variable_api_base(org: Organization) -> str:
    return f"/orgs/{org.login}/actions/variables"


def _get_existing_secret_names(org: Organization, secret_type: str) -> set[str]:
    base = _secret_api_base(org, secret_type)
    try:
        _, data = org._requester.requestJsonAndCheck("GET", base)
        return {s["name"] for s in data.get("secrets", [])}
    except Exception as exc:
        actions_toolkit.warning(f"Could not list org {secret_type} secrets: {exc}")
        return set()


def _get_existing_variable_names(org: Organization) -> set[str]:
    base = _variable_api_base(org)
    try:
        _, data = org._requester.requestJsonAndCheck("GET", base)
        return {v["name"] for v in data.get("variables", [])}
    except Exception as exc:
        actions_toolkit.warning(f"Could not list org variables: {exc}")
        return set()


def _resolve_selected_repo_ids(org: Organization, names: list[str]) -> list[int]:
    ids = []
    for name in names:
        full = name if "/" in name else f"{org.login}/{name}"
        try:
            _, repo_data = org._requester.requestJsonAndCheck("GET", f"/repos/{full}")
            ids.append(repo_data["id"])
        except Exception as exc:
            actions_toolkit.warning(f"Could not resolve repo '{full}': {exc}")
    return ids


# --------------------------------------------------------------------------- #
#  Secrets check / update
# --------------------------------------------------------------------------- #


def check_org_secrets(org: Organization, config_secrets: list[OrgSecret]) -> tuple[bool, dict[str, Any] | None]:
    """Check org-level secrets against expected configuration.

    We can only verify existence (not value) for secrets.
    """
    existing: dict[str, set[str]] = {}
    for s in config_secrets:
        if s.type not in existing:
            existing[s.type] = _get_existing_secret_names(org, s.type)

    missing, extra = [], []
    for s in config_secrets:
        if s.exists is False:
            if s.key in existing.get(s.type, set()):
                extra.append({"name": s.key, "type": s.type})
        else:
            if s.key not in existing.get(s.type, set()):
                missing.append({"name": s.key, "type": s.type})

    result: dict[str, Any] = {}
    if missing:
        result["missing"] = missing
    if extra:
        result["extra"] = extra
    return (False, result) if result else (True, None)


def update_org_secrets(
    org: Organization,
    config_secrets: list[OrgSecret],
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Create or delete org-level secrets to reconcile state with config."""
    errors: list[dict] = []
    messages: list[str] = []

    # Build lookup keyed by (name, type)
    config_by_key: dict[tuple[str, str], OrgSecret] = {(s.key, s.type): s for s in config_secrets}

    for entry in diffs.get("missing", []):
        name, stype = entry["name"], entry["type"]
        s = config_by_key.get((name, stype))
        if s is None:
            continue
        try:
            value = s.expected_value
            if value is None:
                actions_toolkit.warning(f"Skipping org secret '{name}' (env var not set, required=false)")
                continue
            # Encrypt via GitHub public key
            base = _secret_api_base(org, stype)
            _, key_data = org._requester.requestJsonAndCheck("GET", f"{base}/public-key")
            from nacl import encoding, public

            pub_key = public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
            box = public.SealedBox(pub_key)
            encrypted = box.encrypt(value.encode())
            import base64

            encrypted_b64 = base64.b64encode(encrypted).decode()

            payload: dict[str, Any] = {
                "encrypted_value": encrypted_b64,
                "key_id": key_data["key_id"],
                "visibility": s.visibility.value,
            }
            if s.visibility == OrgSecretVisibility.selected and s.selected_repositories:
                payload["selected_repository_ids"] = _resolve_selected_repo_ids(org, s.selected_repositories)

            org._requester.requestJsonAndCheck("PUT", f"{base}/{name}", input=payload)
            actions_toolkit.info(f"Set org {stype} secret '{name}'")
            messages.append(f"Set org {stype} secret '{name}'")
        except SecretEnvError as exc:
            errors.append({"type": "org-secret-create", "name": name, "error": str(exc)})
        except Exception as exc:
            errors.append({"type": "org-secret-create", "name": name, "error": str(exc)})

    for entry in diffs.get("extra", []):
        name, stype = entry["name"], entry["type"]
        base = _secret_api_base(org, stype)
        try:
            org._requester.requestJsonAndCheck("DELETE", f"{base}/{name}")
            actions_toolkit.info(f"Deleted org {stype} secret '{name}'")
            messages.append(f"Deleted org {stype} secret '{name}'")
        except Exception as exc:
            errors.append({"type": "org-secret-delete", "name": name, "error": str(exc)})

    return errors, messages


# --------------------------------------------------------------------------- #
#  Variables check / update
# --------------------------------------------------------------------------- #


def check_org_variables(org: Organization, config_variables: list[OrgSecret]) -> tuple[bool, dict[str, Any] | None]:
    """Check org-level Actions variables against expected configuration."""
    existing_names = _get_existing_variable_names(org)

    missing: list[str] = []
    extra: list[str] = []
    wrong_value: dict[str, Any] = {}

    # Fetch all variable values for comparison
    base = _variable_api_base(org)
    existing_values: dict[str, str] = {}
    try:
        _, data = org._requester.requestJsonAndCheck("GET", base)
        for v in data.get("variables", []):
            existing_values[v["name"]] = v.get("value", "")
    except Exception:
        pass

    for v in config_variables:
        if v.exists is False:
            if v.key in existing_names:
                extra.append(v.key)
            continue
        if v.key not in existing_names:
            missing.append(v.key)
        else:
            try:
                expected = v.expected_value
            except SecretEnvError:
                continue
            if expected is not None and existing_values.get(v.key) != expected:
                wrong_value[v.key] = {"expected": expected, "found": existing_values.get(v.key)}

    result: dict[str, Any] = {}
    if missing:
        result["missing"] = missing
    if extra:
        result["extra"] = extra
    if wrong_value:
        result["wrong_value"] = wrong_value
    return (False, result) if result else (True, None)


def update_org_variables(
    org: Organization,
    config_variables: list[OrgSecret],
    diffs: dict[str, Any],
) -> tuple[list[dict], list[str]]:
    """Create, update, or delete org-level Actions variables."""
    errors: list[dict] = []
    messages: list[str] = []
    config_by_key = {v.key: v for v in config_variables}
    base = _variable_api_base(org)

    for name in diffs.get("missing", []):
        v = config_by_key[name]
        try:
            value = v.expected_value
            if value is None:
                actions_toolkit.warning(f"Skipping org variable '{name}' (env var not set, required=false)")
                continue
            payload: dict[str, Any] = {
                "name": name,
                "value": value,
                "visibility": v.visibility.value,
            }
            if v.visibility == OrgSecretVisibility.selected and v.selected_repositories:
                payload["selected_repository_ids"] = _resolve_selected_repo_ids(org, v.selected_repositories)
            org._requester.requestJsonAndCheck("POST", base, input=payload)
            actions_toolkit.info(f"Created org variable '{name}'")
            messages.append(f"Created org variable '{name}'")
        except SecretEnvError as exc:
            errors.append({"type": "org-variable-create", "name": name, "error": str(exc)})
        except Exception as exc:
            errors.append({"type": "org-variable-create", "name": name, "error": str(exc)})

    for name in diffs.get("extra", []):
        try:
            org._requester.requestJsonAndCheck("DELETE", f"{base}/{name}")
            actions_toolkit.info(f"Deleted org variable '{name}'")
            messages.append(f"Deleted org variable '{name}'")
        except Exception as exc:
            errors.append({"type": "org-variable-delete", "name": name, "error": str(exc)})

    for name in diffs.get("wrong_value", {}).keys():
        v = config_by_key[name]
        try:
            value = v.expected_value
            if value is None:
                continue
            payload = {"name": name, "value": value, "visibility": v.visibility.value}
            if v.visibility == OrgSecretVisibility.selected and v.selected_repositories:
                payload["selected_repository_ids"] = _resolve_selected_repo_ids(org, v.selected_repositories)
            org._requester.requestJsonAndCheck("PATCH", f"{base}/{name}", input=payload)
            actions_toolkit.info(f"Updated org variable '{name}'")
            messages.append(f"Updated org variable '{name}'")
        except SecretEnvError as exc:
            errors.append({"type": "org-variable-update", "name": name, "error": str(exc)})
        except Exception as exc:
            errors.append({"type": "org-variable-update", "name": name, "error": str(exc)})

    return errors, messages
