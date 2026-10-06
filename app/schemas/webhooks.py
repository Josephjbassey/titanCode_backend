from pydantic import BaseModel, ConfigDict
from typing import Any, Optional


class PaystackWebhookEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event: str
    data: dict[str, Any]


class FlutterwaveWebhookEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event: str
    data: dict[str, Any]


class SumsubWebhookEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    applicantId: Optional[str] = None
    externalUserId: Optional[str] = None
    reviewResult: Optional[dict[str, Any]] = None
    reviewStatus: Optional[str] = None
    createdAtMs: Optional[int] = None


class StripeWebhookEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    type: str
    data: dict[str, Any]
