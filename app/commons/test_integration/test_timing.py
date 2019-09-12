import pytest
from typing import List
from app.commons.database.infra import DB
from app.commons.utils.testing import Stat


class MyRepository:
    def __init__(self, db: DB):
        self.db = db

    async def insert_name(self):
        return await self.db.master().fetch_value("SELECT 1")

    async def get_name_replica(self):
        return await self.db.replica().fetch_value("SELECT 3")

    async def with_transaction(self):
        async with self.db.master().transaction() as transaction:
            connection = transaction.connection()
            return await self.insert_conn(connection)

    async def insert_conn(self, connection):
        return await connection.fetch_value("SELECT 2")


class TestTiming:
    pytestmark = [pytest.mark.asyncio]

    @pytest.fixture(autouse=True)
    def setup(self, service_statsd_client):
        # ensure that we mock the statsd service client
        ...

    async def test_stats_query(
        self, payin_maindb: DB, get_mock_statsd_events, reset_mock_statsd_events
    ):
        repository = MyRepository(payin_maindb)

        # master
        assert await repository.insert_name() == 1
        events: List[Stat] = get_mock_statsd_events()
        assert len(events) == 1
        event = events[0]
        assert event.stat_name == "dd.pay.payment-service.io.db.latency"
        assert event.tags == {
            "database_name": "payin_maindb",
            "instance_name": "master",
            "query_name": "insert_name",
        }

        # reset
        reset_mock_statsd_events()
        events = get_mock_statsd_events()
        assert len(events) == 0

        # replica
        assert await repository.get_name_replica() == 3
        events = get_mock_statsd_events()
        assert len(events) == 1
        event = events[0]
        assert event.stat_name == "dd.pay.payment-service.io.db.latency"
        assert event.tags == {
            "database_name": "payin_maindb",
            "instance_name": "replica",
            "query_name": "get_name_replica",
        }

    async def test_stats_transaction(self, payin_maindb: DB, get_mock_statsd_events):
        repository = MyRepository(payin_maindb)

        assert await repository.with_transaction() == 2

        events: List[Stat] = get_mock_statsd_events()
        assert len(events) == 2, "transaction and query"
        stat_names = {
            (event.stat_name, event.tags["query_name"]): event for event in events
        }

        # query
        insert_name = ("dd.pay.payment-service.io.db.latency", "insert_conn")
        assert insert_name in stat_names
        insert_query = stat_names[insert_name]
        assert insert_query.tags == {
            "database_name": "payin_maindb",
            "instance_name": "master",
            "transaction_name": "with_transaction",
            "query_name": "insert_conn",
        }

        # transaction
        transaction_name = ("dd.pay.payment-service.io.db.latency", "with_transaction")
        assert transaction_name in stat_names, "transaction exists"
        transaction = stat_names[transaction_name]
        assert transaction.tags == {
            "database_name": "payin_maindb",
            "instance_name": "master",
            # "transaction_name": "with_transaction",
            "query_type": "transaction",
            "query_name": "with_transaction",
        }