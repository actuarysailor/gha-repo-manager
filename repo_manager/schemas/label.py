from typing import Optional

from pydantic import BaseModel, ValidationInfo, Field, field_validator  # pylint: disable=E0611
from pydantic_extra_types.color import Color

OptBool = Optional[bool]
OptStr = Optional[str]


class Label(BaseModel):
    name: str = Field(description="Label's name.")
    color: Color | None = Field(None, description="Color of this label")
    description: OptStr = Field(None, description="Description of the label")
    new_name: OptStr = Field(None, description="If set, rename a label from name to new_name.")
    exists: OptBool = Field(True, description="Set to false to delete a label")

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: str, info: ValidationInfo) -> str:
        if v is None:
            raise ValueError("Missing name of label!")
        return v

    @property
    def expected_name(self) -> str:
        """What the expected label name of this label is. If new_name is set, it will be new_name. Otherwise, name"""
        return self.new_name if self.new_name is not None else self.name

    @property
    def color_no_hash(self) -> str:
        """Returns the color without the leader # if it exists"""
        return self.color if self.color is None else str(self.color._original).replace("#", "")
