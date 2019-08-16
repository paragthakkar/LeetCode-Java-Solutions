from datetime import datetime
from typing import Optional
from uuid import UUID

from asyncpg import DataError, UniqueViolationError
from pydantic import Json

from app.commons.context.app_context import AppContext
from app.commons.context.req_context import ReqContext
from app.ledger.core.mx_transaction.exceptions import (
    MxTransactionCreationError,
    LedgerErrorCode,
    ledger_error_message_maps,
)
from app.ledger.core.mx_transaction.utils import to_mx_transaction
from app.ledger.repository.mx_transaction_repository import (
    MxTransactionRepository,
    InsertMxTransactionWithLedgerInput,
)
from app.ledger.core.mx_transaction.model import MxTransaction
from app.ledger.core.mx_transaction.types import (
    MxTransactionType,
    MxScheduledLedgerIntervalType,
    MxLedgerType,
)
from app.ledger.repository.mx_ledger_repository import (
    GetMxLedgerByAccountInput,
    MxLedgerRepository,
)
from app.ledger.repository.mx_scheduled_ledger_repository import (
    GetMxScheduledLedgerInput,
    MxScheduledLedgerRepository,
)


async def create_mx_transaction_impl(
    app_context: AppContext,
    req_context: ReqContext,
    mx_transaction_repository: MxTransactionRepository,
    mx_ledger_repository: MxLedgerRepository,
    mx_scheduled_ledger_repository: MxScheduledLedgerRepository,
    payment_account_id: str,
    target_type: MxTransactionType,
    amount: int,
    currency: str,
    idempotency_key: str,
    routing_key: datetime,
    interval_type: MxScheduledLedgerIntervalType,
    target_id: Optional[str] = None,
    context: Optional[Json] = None,
    metadata: Optional[Json] = None,
    legacy_transaction_id: Optional[str] = None,
) -> MxTransaction:
    """
    Get or create mx_ledger and mx_scheduled_ledger and create mx_txn attached and update corresponding balance
    """
    req_context.log.info(
        "[create_mx_transaction_impl] payment_account_id:%s, target_type:%s",
        payment_account_id,
        target_type.value,
    )
    # with given payment_account_id, routing_key and interval_type, retrieve open scheduled ledger
    get_scheduled_ledger_request = GetMxScheduledLedgerInput(
        payment_account_id=payment_account_id,
        routing_key=routing_key,
        interval_type=interval_type,
    )
    mx_scheduled_ledger = await mx_scheduled_ledger_repository.get_open_mx_scheduled_ledger_for_period(
        get_scheduled_ledger_request
    )
    # if not found, retrieve open ledger for current payment_account
    if not mx_scheduled_ledger:
        get_mx_ledger_request = GetMxLedgerByAccountInput(
            payment_account_id=payment_account_id
        )
        mx_ledger = await mx_ledger_repository.get_open_ledger_for_payment_account(
            get_mx_ledger_request
        )
        # if not found, create new mx_scheduled_ledger and mx_ledger
        if not mx_ledger:
            # construct input and insert
            request_input = InsertMxTransactionWithLedgerInput(
                currency=currency,
                amount=amount,
                type=MxLedgerType.SCHEDULED,
                payment_account_id=payment_account_id,
                interval_type=interval_type,
                routing_key=routing_key,
                idempotency_key=idempotency_key,
                target_type=target_type,
                legacy_transaction_id=legacy_transaction_id,
                target_id=target_id,
                context=context,
                metadata=metadata,
            )
            try:
                created_mx_txn = await mx_transaction_repository.create_ledger_and_insert_mx_transaction(
                    request_input, mx_scheduled_ledger_repository, req_context
                )
            except DataError as e:
                req_context.log.error(
                    "[create_ledger_and_insert_mx_transaction] Invalid input data while inserting mx transaction and creating ledger",
                    e,
                )

                raise MxTransactionCreationError(
                    error_code=LedgerErrorCode.MX_TXN_CREATE_ERROR,
                    error_message=ledger_error_message_maps[
                        LedgerErrorCode.MX_TXN_CREATE_ERROR.value
                    ],
                    retryable=True,
                )
            except UniqueViolationError as e:
                req_context.log.error(
                    "[create_ledger_and_insert_mx_transaction] Unique constriants violated while inserting mx_ledger",
                    e,
                )
                # todo: retry with insert_mx_txn_and_update_ledger
                raise MxTransactionCreationError(
                    error_code=LedgerErrorCode.MX_LEDGER_CREATE_UNIQUE_VIOLATION_ERROR,
                    error_message=ledger_error_message_maps[
                        LedgerErrorCode.MX_LEDGER_CREATE_UNIQUE_VIOLATION_ERROR.value
                    ],
                    retryable=True,
                )
            except Exception as e:
                req_context.log.error(
                    "[create_ledger_and_insert_mx_transaction] Exception caught while inserting mx transaction and creating ledger",
                    e,
                )
                raise e

            return to_mx_transaction(created_mx_txn)
        # found open ledger, create transaction attach to it and update balance
        request_input = InsertMxTransactionWithLedgerInput(
            currency=currency,
            amount=amount,
            type=MxLedgerType.SCHEDULED,
            payment_account_id=payment_account_id,
            interval_type=interval_type,
            routing_key=routing_key,
            idempotency_key=idempotency_key,
            target_type=target_type,
            legacy_transaction_id=legacy_transaction_id,
            target_id=target_id,
            context=context,
            metadata=metadata,
        )
        created_mx_txn = await insert_mx_txn_and_update_ledger(
            mx_ledger_repository,
            mx_transaction_repository,
            mx_ledger.id,
            request_input,
            req_context,
        )
        return to_mx_transaction(created_mx_txn)

    # if mx_scheduled_ledger found, retrieve the corresponding mx_ledger, create transaction attached and update balance
    request_input = InsertMxTransactionWithLedgerInput(
        currency=currency,
        amount=amount,
        type=MxLedgerType.SCHEDULED,
        payment_account_id=payment_account_id,
        interval_type=interval_type,
        routing_key=routing_key,
        idempotency_key=idempotency_key,
        target_type=target_type,
        target_id=target_id,
        context=context,
        metadata=metadata,
    )
    created_mx_txn = await insert_mx_txn_and_update_ledger(
        mx_ledger_repository,
        mx_transaction_repository,
        mx_scheduled_ledger.ledger_id,
        request_input,
        req_context,
    )
    return to_mx_transaction(created_mx_txn)


async def insert_mx_txn_and_update_ledger(
    mx_ledger_repository: MxLedgerRepository,
    mx_transaction_repository: MxTransactionRepository,
    ledger_id: UUID,
    request_input: InsertMxTransactionWithLedgerInput,
    req_context: ReqContext,
):

    try:
        created_mx_txn = await mx_transaction_repository.insert_mx_transaction_and_update_ledger(
            request_input, mx_ledger_repository, ledger_id, req_context
        )
    except DataError as e:
        req_context.log.error(
            "[insert_mx_transaction_and_update_ledger] Invalid input data while inserting mx transaction and updating ledger",
            e,
        )
        raise MxTransactionCreationError(
            error_code=LedgerErrorCode.MX_TXN_CREATE_ERROR,
            error_message=ledger_error_message_maps[
                LedgerErrorCode.MX_TXN_CREATE_ERROR.value
            ],
            retryable=True,
        )
    except Exception as e:
        req_context.log.error(
            "[insert_mx_transaction_and_update_ledger] Exception caught while inserting mx transaction and updating ledger",
            e,
        )
        raise e
    return created_mx_txn
