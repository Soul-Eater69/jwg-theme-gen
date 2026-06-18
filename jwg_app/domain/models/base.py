from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def to_camel(string: str) -> str:
    """
    Convert string to camelCase. camelCase starts with a lower case alphabetic
    character, the rest of the string contains alphanumeric characters.
    Any character case in the input is ignored. Any spaces in the input
    capitalise the following character if alphabetic,
    except for the first character. Any non-alphanumeric characters
    are ignored.

    :param string: The input string.
    :return: The input converted to camelCase; empty ('')
        if there are no valid characters in the input string.
    :raises: AssertionError if the input is not of type str.
    """

    assert isinstance(string, str), "Input must be of type str"

    first_alphabetic_character_index = -1
    for index, character in enumerate(string):
        if character.isalpha():
            first_alphabetic_character_index = index
            break

    empty = ""

    if first_alphabetic_character_index == -1:
        return empty

    string = string[first_alphabetic_character_index:]

    titled_string_generator = (
        character for character in string.title() if character.isalnum()
    )

    try:
        return next(titled_string_generator).lower() + empty.join(
            titled_string_generator
        )

    except StopIteration:
        return empty


class CamelModel(BaseModel):
    class Config:
        alias_generator = to_camel
        populate_by_name = True

    def model_dump(self, **kwargs):
        kwargs.pop("by_alias", None)
        return super().model_dump(**kwargs, by_alias=True)


class AuthInfo(BaseModel):
    user_id: str = Field(...)
    bearer_token: str = Field(...)
    email: str = Field(...)
    display_name: str = Field(...)


class Property(CamelModel):
    property_name: str = Field(...)
    property_value: Any = Field(...)


class RecordState(str, Enum):
    CREATED = "C"
    UPDATED = "U"
    DELETED = "D"


class WorkletType(str, Enum):
    USER_STORY = "USER_STORY"
    TEST_CASE = "TEST_CASE"
    TEST_STEP = "TEST_STEP"
    ENGAGEMENT_REQUEST = "ENGAGEMENT_REQUEST"
    EPIC = "EPIC"
    PRODUCT_MODIFICATION = "PRODUCT_MODIFICATION"
    THEME = "THEME"
    VALUE_STREAM = "VALUE_STREAM"


class DataSource(str, Enum):
    TG = "TG"
    JIRA = "JIRA"


class CoverageColor(str, Enum):
    GREEN = "green"


class CreativityColor(str, Enum):
    ORANGE = "orange"


class JIRAUser(CamelModel):
    """User information."""

    lan_id: str = Field(..., description="Unique identifier for the user")
    email: str = Field(..., description="User's email address")
    display_name: str = Field(..., description="User's display name")


class PushToJiraUserDetail(CamelModel):
    """Model for tracking user who pushed the story to JIRA with timestamp"""

    email: str = Field(
        ..., description="Email ID of the user who pushed the story to JIRA"
    )
    lan_id: str = Field(
        ..., description="Lan ID of the user who pushed the story to JIRA"
    )
    display_name: str = Field(
        ..., description="Display name of the user who pushed the story to JIRA"
    )
    timestamp: str = Field(
        ..., description="Timestamp when the user story was pushed to JIRA"
    )


class ThemeStatus(str, Enum):
    IN_REVIEW = "In Review"
    PUSHED_TO_JIRA = "Pushed to JIRA"


class EngagementRequestAction(str, Enum):
    GENERATE = "GENERATE"
    ANALYSE = "ANALYSE"
    VALIDATE = "VALIDATE"
    SYNC_ASSIGNEE = "SYNC_ASSIGNEE"
    FEEDBACK = "FEEDBACK"


class ValueStreamAction(str, Enum):
    GENERATE = "GENERATE"


class ThemeAction(str, Enum):
    PUSH_TO_JIRA = "PUSH_TO_JIRA"
    FEEDBACK = "FEEDBACK"
