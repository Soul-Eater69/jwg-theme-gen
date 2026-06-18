from __future__ import annotations

import json
import logging
import os
import re
import uuid
from functools import partial
from typing import Any, Dict, List, Optional

import httpx
from jira import JIRAFieldProvider
import yaml
from worklet_data_api import WorkletState

from jwg_app.domain.exceptions.custom_exception import CustomException
from jwg_app.infrastructure.external.platform_rest_client import PlatformRestClient
from jwg_app.domain.services.constants import (
    LOGICAL_TO_JIRA_FIELD_MAPPING,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


## place holder function for the Linked stories and epics for the given prodmod id.fetch_epics_and_stories
# TODO: Change the function for the required json
def retrive_additional_data(prodmod_id: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Fetches the list of epics and stories for a given Product Modification ID by triggering an API call.

    Parameters
    ----------
    prodmod_id : str
        The Product Modification ID for which epics and stories need to be fetched.

    Returns
    -------
    Dict[str, List[Dict[str, str]]]
        A dictionary containing lists of epics and stories.
        Example:
        {
            "epics": [
                {"summary": "Epic 1 Summary", "description": "Epic 1 Description", "success_criteria": "Epic 1 Success Criteria"},
                {"summary": "Epic 2 Summary", "description": "Epic 2 Description", "success_criteria": "Epic 2 Success Criteria"}
            ],
            "stories": [
                {"summary": "Story 1 Summary", "description": "Story 1 Description"},
                {"summary": "Story 2 Summary", "description": "Story 2 Description"}
            ]
        }
    """
    api_url = f"https://example.com/api/prodmod/{prodmod_id}/epics-and-stories"  # Replace with actual API URL
    try:
        response = httpx.get(
            api_url, timeout=10
        )  # Use httpx for async support if needed
        response.raise_for_status()
        data = response.json()
        return {
            "epics": [
                {
                    "summary": epic.get("summary", ""),
                    "description": epic.get("description", ""),
                    "success_criteria": epic.get("success_criteria", ""),
                }
                for epic in data.get("epics", [])
            ],
            "stories": [
                {
                    "summary": story.get("summary", ""),
                    "description": story.get("description", ""),
                }
                for story in data.get("stories", [])
            ],
        }
    except httpx.RequestError as e:
        logger.error(f"An error occurred while fetching epics and stories: {e}")
        return {"epics": [], "stories": []}
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        )
        return {"epics": [], "stories": []}


def generate_unique_id(prefix: str = None) -> str:
    """Generates a unique UUID with any given prefix as prefix-UUID
    Parameters
    ----------
    prefix : str, optional
        Prefix to add before UUID, if not specified, prefix will be empty and only UUID will be returned, by default None
    Returns
    -------
    str
        Unique ID
    """
    prefix = "" if prefix is None else prefix + "-"
    return prefix + str(uuid.uuid4())


def load_yml(path: str) -> dict:
    """Parse YAML file and return its contents

    Parameters
    ----------
    path : str
        Path containing YAML file

    Returns
    -------
    dict
        Contents of YAML file
    """
    with open(path, "r") as f:
        return yaml.safe_load(f.read())


class DotifyDict(dict):
    """
    Converts a dictionary into Dotify format

    Parameters
    ----------
    dict : dict
        Dictionary to convert to Dotify format

    Returns
    -------
    DotifyDict
        Dotify format of the given dict

    Raises
    ------
    TypeError
        If provided value is not a dictionary

    Examples
    --------
    >>> dict = {"apples": 5, "oranges": 6}
    >>> dict = DotifyDict(dict)
    >>> dict.apples
        5
    >>> dict.oranges
        6
    """

    MARKER = object()

    def __init__(self, value=None):
        if value is None:
            pass
        elif isinstance(value, dict):
            for key in value:
                self.__setitem__(key, value[key])
        else:
            raise TypeError("expected dict")

    def __setitem__(self, key, value):
        if isinstance(value, dict) and not isinstance(value, DotifyDict):
            value = DotifyDict(value)
        super(DotifyDict, self).__setitem__(key, value)

    def __getitem__(self, key):
        found = self.get(key, DotifyDict.MARKER)
        if found is DotifyDict.MARKER:
            found = DotifyDict()
            super(DotifyDict, self).__setitem__(key, found)
        return found

    __setattr__, __getattr__ = __setitem__, __getitem__


def load_config(config_file: str) -> DotifyDict:
    """Loads YAML config file and returns a DotifyDict object

    Parameters
    ----------
    config_file : str
        YAML config file

    Returns
    -------
    DotifyDict
        Dotify dict object of the YAML config file

    Raises
    ------
    FileNotFoundError
        If the config file doesn't exist at the `config_file` path
    """
    if not os.path.isfile(config_file):
        raise FileNotFoundError(f"Config file doesn't exist at {config_file}")

    def _dotted_access_getter(key, dct):
        for k in key.split("."):
            dct = dct[k]
        return dct

    def _repl_fn(match_obj, getter):
        return getter(match_obj.groups()[0])

    def _interpolate(val, repl_fn):
        if isinstance(val, dict):
            return {k: _interpolate(v, repl_fn) for k, v in val.items()}
        elif isinstance(val, list):
            return [_interpolate(v, repl_fn) for v in val]
        elif isinstance(val, str):
            return re.sub(r"\$\(([\w.]+)\)", repl_fn, val)
        else:
            return val

    cfg = load_yml(config_file)

    cfg = _interpolate(
        cfg,
        partial(_repl_fn, getter=partial(_dotted_access_getter, dct=cfg)),
    )

    return DotifyDict(cfg)


def filter_project_fields_data(
    project_fields_data: Dict[str, Any], filterable_fields: List[str]
) -> Dict[str, Any]:
    filtered_data = {
        "maxResults": project_fields_data.get("maxResults", 0),
        "startAt": project_fields_data.get("startAt", 0),
        "total": 0,  # Will update this after filtering
        "isLast": project_fields_data.get("isLast", True),
        "values": [],
    }

    # Filter the values array
    if "values" in project_fields_data and isinstance(
        project_fields_data["values"], list
    ):
        # First filter by field names
        filtered_values = []
        for item in project_fields_data["values"]:
            if "name" in item and item["name"] in filterable_fields:
                # Create a new object with only the required fields
                filtered_item = {}

                # Only keep required, name, and allowedValues properties
                if "required" in item:
                    filtered_item["required"] = item["required"]
                if "name" in item:
                    filtered_item["name"] = item["name"]

                if "allowedValues" in item and isinstance(item["allowedValues"], list):
                    filtered_allowed_values = []
                    for allowed_value in item["allowedValues"]:
                        # Skip values where disabled is true
                        if allowed_value.get("disabled") == True:
                            continue

                        filtered_allowed_value = {}
                        # Only keep id and value properties
                        if "id" in allowed_value:
                            filtered_allowed_value["id"] = allowed_value["id"]
                        if "value" in allowed_value:
                            filtered_allowed_value["value"] = allowed_value["value"]

                        # Also process children array if it exists
                        if "children" in allowed_value and isinstance(
                            allowed_value["children"], list
                        ):
                            filtered_children = []
                            for child in allowed_value["children"]:
                                # Skip children with disabled: true
                                if child.get("disabled") == True:
                                    continue

                                filtered_child = {}
                                # Only keep id and value properties for children too
                                if "id" in child:
                                    filtered_child["id"] = child["id"]
                                if "value" in child:
                                    filtered_child["value"] = child["value"]

                                # Only add to filtered children if we have at least one of id or value
                                if filtered_child:
                                    filtered_children.append(filtered_child)

                            # Only add children array if it's not empty
                            if filtered_children:
                                filtered_allowed_value["children"] = filtered_children

                        # Only add to filtered values if we have at least one of id or value
                        if filtered_allowed_value:
                            filtered_allowed_values.append(filtered_allowed_value)

                    filtered_item["allowedValues"] = filtered_allowed_values

                filtered_values.append(filtered_item)

        filtered_data["values"] = filtered_values
        filtered_data["total"] = len(filtered_values)

    return filtered_data


async def extract_error_status_and_message(error) -> Dict[str, Any]:
    """
    Utility to extract status code and error message from error object or tuple.
    Returns a dict with 'statusCode' and 'errorMessage'.
    """
    status_code = 400
    error_msg = str(error)

    if isinstance(error, CustomException):
        status_code = error.status_code
        error_msg = error.detail
    elif isinstance(error, tuple) and len(error) == 2:
        match = re.match(r"(\d+):\s*(.*)", error[1])
        if match:
            status_code = int(match.group(1))
            error_msg = match.group(2)
        else:
            error_msg = error[1]
        # Try to extract the errors field from the JSON in the error message
        json_match = re.search(r"(\{.*\})", error_msg)
        if json_match:
            try:
                error_json = json.loads(json_match.group(1))
                if "errors" in error_json:
                    error_msg = error_json["errors"]
            except Exception:
                pass  # fallback to original error_msg if JSON parsing fails

        # If error_msg is a dict, concatenate its values
        if isinstance(error_msg, dict):
            error_msg = ", ".join(str(v).rstrip(".") for v in error_msg.values())

    return {
        "statusCode": status_code,
        "errorMessage": error_msg,
    }


# NOTE: `retrieve_similar_entities` is part of this prod file but its body is cut off in the
# screenshot (truncated mid-function around line 388). Send the remainder and I'll add it verbatim;
# I am intentionally not inventing the rest.
