from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    personality: str = Field(default="Warm, respectful and clear.", max_length=2000)
    writing_style: str = Field(
        default="Brief, natural messages. Disclose that you are an AI assistant.", max_length=2000
    )
    chat_language: str = Field(default="Diana HE · spoiled GFE · wealthy TA", max_length=80)
    languages: str = Field(default="English", max_length=300)
    pricing: str = Field(default="", max_length=2000)
    availability: str = Field(default="", max_length=2000)
    boundaries: str = Field(
        default="Non-sexual social companionship only. Adults only. Public venues.", max_length=2000
    )
    meeting_rules: str = Field(
        default="Meetings require human confirmation. No payment collection in chat.", max_length=2000
    )
    instructions: str = Field(default="", max_length=4000)


class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    owner_telegram_id: int = Field(gt=0, le=2**52)
    mode: Literal["auto", "approval", "human"] = "approval"
    enabled: bool = False
    lawful_reviewed: bool = False
    config: ProfileConfig = Field(default_factory=ProfileConfig)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["allow", "escalate", "block"]
    reason: Literal[
        "safe",
        "sexual_services",
        "minors",
        "coercion",
        "trafficking",
        "illegal_activity",
        "uncertain",
        "booking",
        "privacy",
        "human_request",
    ]
    reply: str = Field(max_length=3500)
