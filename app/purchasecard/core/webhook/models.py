from typing import List, Optional

from pydantic import BaseModel


class Response(BaseModel):
    code: str


class GatewayLog(BaseModel):
    timed_out: bool


class Funding(BaseModel):
    gateway_log: GatewayLog


class GpaOrder(BaseModel):
    funding: Funding


class Transaction(BaseModel):
    token: str
    response: Response
    gpa_order: Optional[GpaOrder]
    type: str
    state: str
    user_token: str


class TransactionProcessResult(BaseModel):
    transaction_token: str
    user_token: str
    process_type: str
    delivery_id: Optional[int]
    amount: Optional[int]
    card_acceptor: Optional[str]


class TransactionProcessResults(BaseModel):
    processed_results: List[TransactionProcessResult]