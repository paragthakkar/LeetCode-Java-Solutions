from fastapi import APIRouter, Depends
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR, HTTP_201_CREATED

from app.commons.api.models import PaymentErrorResponseBody, PaymentException
from app.commons.core.errors import PaymentError
from app.purchasecard.api.auth.v0.models import CreateAuthResponse, CreateAuthRequest
from app.purchasecard.container import PurchaseCardContainer
from app.purchasecard.core.auth.models import (
    InternalCreateAuthResponse,
    InternalStoreInfo,
)
from app.purchasecard.core.auth.processor import AuthProcessor

api_tags = ["AuthV0"]
router = APIRouter()


@router.post(
    "",
    status_code=HTTP_201_CREATED,
    operation_id="CreateAuth",
    response_model=CreateAuthResponse,
    responses={HTTP_500_INTERNAL_SERVER_ERROR: {"model": PaymentErrorResponseBody}},
    tags=api_tags,
)
async def create_auth(
    request: CreateAuthRequest,
    dependency_container: PurchaseCardContainer = Depends(PurchaseCardContainer),
):
    try:
        auth_processor: AuthProcessor = dependency_container.auth_processor
        internal_store_info = InternalStoreInfo(
            store_id=request.store_meta.store_id,
            store_city=request.store_meta.store_city,
            store_business_name=request.store_meta.store_business_name,
        )
        response: InternalCreateAuthResponse = await auth_processor.create_auth(
            subtotal=request.subtotal,
            subtotal_tax=request.subtotal_tax,
            store_meta=internal_store_info,
            delivery_id=request.delivery_id,
            delivery_requires_purchase_card=request.delivery_requires_purchase_card,
            shift_id=request.shift_id,
            ttl=request.ttl,
        )
        return CreateAuthResponse(
            delivery_id=response.delivery_id,
            created_at=response.created_at,
            updated_at=response.updated_at,
        )
    except PaymentError as e:
        status = HTTP_500_INTERNAL_SERVER_ERROR
        raise PaymentException(
            http_status_code=status,
            error_code=e.error_code,
            error_message=e.error_message,
            retryable=e.retryable,
        )