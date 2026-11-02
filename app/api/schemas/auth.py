"""Local POC account request and response schemas."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CompanyId = Literal["ceat", "kec", "zensar", "harrisons"]


class SignUpRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=2, max_length=100)
    company: CompanyId
    expert_opt_in: bool = False
    expert_title: str = Field(default="", max_length=120)
    expert_skills: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @model_validator(mode="after")
    def validate_expert_opt_in(self) -> "SignUpRequest":
        if self.expert_opt_in and (not self.expert_title.strip() or not self.expert_skills):
            raise ValueError("Expert opt-in requires a job title and at least one skill")
        return self


class SignInRequest(BaseModel):
    email: str
    password: str


class AccountResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict