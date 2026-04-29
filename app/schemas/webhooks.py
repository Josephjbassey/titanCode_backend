from pydantic import BaseModel
from typing import Any


class PaystackWebhookEnvelope(BaseModel):
    event: str
    data: dict[str, Any]


class FlutterwaveWebhookEnvelope(BaseModel):
    event: str
    data: dict[str, Any]
