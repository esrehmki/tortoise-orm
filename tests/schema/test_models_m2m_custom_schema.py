"""
This example demonstrates SQL Schema generation for each DB type supported with a custom schema name.
"""
from tests import testmodels_postgres as testmodels
from tortoise.contrib import test
from tortoise.exceptions import IntegrityError, OperationalError


@test.requireCapability(dialect="postgres")
class TestCustomSchema(test.IsolatedTestCase):
    tortoise_test_modules = ["tests.testmodels_postgres"]

    async def _setUpDB(self) -> None:
        try:
            await super()._setUpDB()
        except OperationalError:
            raise test.SkipTest("Works only with PostgreSQL")

    async def test_create(self):
        tournament: testmodels.Tournament = await testmodels.Tournament.create(name="T")
        reporter: testmodels.Reporter = await testmodels.Reporter.create(name="R")
        event: testmodels.Event = await testmodels.Event.create(
            name="E", tournament=tournament, reporter=reporter
        )
        team: testmodels.Team = await testmodels.Team.create(name="TE")

        actual_tournament: testmodels.Tournament = await testmodels.Tournament.get(id=tournament.id)
        self.assertEqual(tournament, actual_tournament)
        actual_reporter: testmodels.Reporter = await testmodels.Reporter.get(id=reporter.id)
        self.assertEqual(reporter, actual_reporter)
        actual_event: testmodels.Event = await testmodels.Event.get(id=event.id)
        self.assertEqual(event, actual_event)
        actual_team: testmodels.Team = await testmodels.Team.get(id=team.id)
        self.assertEqual(team, actual_team)

    async def test_update(self):
        await self.test_create()

        expected_tournament_name: str = "Tournament"
        await testmodels.Tournament.filter(id=1).update(name=expected_tournament_name)
        self.assertEqual(expected_tournament_name, (await testmodels.Tournament.get(id=1)).name)

        expected_reporter_name: str = "Reporter"
        await testmodels.Reporter.filter(id=1).update(name=expected_reporter_name)
        self.assertEqual(expected_reporter_name, (await testmodels.Reporter.get(id=1)).name)

        expected_event_name: str = "Event"
        await testmodels.Event.filter(id=1).update(name=expected_event_name)
        self.assertEqual(expected_event_name, (await testmodels.Event.get(id=1)).name)

        expected_team_name: str = "Team"
        await testmodels.Team.filter(id=1).update(name=expected_team_name)
        self.assertEqual(expected_team_name, (await testmodels.Team.get(id=1)).name)

    async def test_m2m_relation(self):
        await self.test_create()
        actual_event: testmodels.Event = await testmodels.Event.get(id=1)
        actual_team: testmodels.Team = await testmodels.Team.get(id=1)

        await actual_event.participants.add(actual_team)

        async for participant in actual_event.participants:
            self.assertEqual("TE", participant.name)

        ret_val = await testmodels.Event.filter(participants__id=1).first()
        pass
