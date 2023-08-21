from tortoise import Model, fields
from tortoise.fields.base import OnDelete
from tortoise.contrib.postgres.fields import ArrayField

from tests.testmodels import generate_token


class ArrayFields(Model):
    id = fields.IntField(pk=True)
    array = ArrayField()
    array_null = ArrayField(null=True)


# models to test schemas other than 'public'
class Tournament(Model):
    id = fields.SmallIntField(pk=True)
    name = fields.CharField(max_length=255)
    desc = fields.TextField(null=True)
    created = fields.DatetimeField(auto_now_add=True, index=True)

    events: fields.ReverseRelation["Event"]

    class Meta:
        schema = "test_schema"
        table_description = "What Tournaments */'`/* we have"

    def __str__(self):
        return self.name


class Reporter(Model):
    id = fields.IntField(pk=True)
    name = fields.TextField()

    events: fields.ReverseRelation["Event"]

    class Meta:
        schema = "test_schema"

    def __str__(self):
        return self.name


class Event(Model):
    id = fields.IntField(pk=True)
    name = fields.TextField()
    modified = fields.DatetimeField(auto_now=True)
    token = fields.CharField(
        default=generate_token, max_length=100, description="Unique token", unique=True
    )
    alias = fields.IntField(null=True)

    tournament: fields.ForeignKeyRelation["Tournament"] = fields.ForeignKeyField(
        model_name="models.Tournament", related_name="events"
    )
    reporter: fields.ForeignKeyNullableRelation[Reporter] = fields.ForeignKeyField(
        model_name="models.Reporter", null=True
    )
    participants: fields.ManyToManyRelation["Team"] = fields.ManyToManyField(
        model_name="models.Team",
        related_name="events",
        through="event_team",
        on_delete=OnDelete.SET_NULL,
        description="How participants relate",
    )

    class Meta:
        schema = "test_schema"
        table_description = "This table contains a list of all the events"
        unique_together = [("name", "token"), ["tournament", "id"]]

    def __str__(self):
        return self.name


class Team(Model):
    id = fields.IntField(pk=True)
    name = fields.TextField()
    alias = fields.IntField(null=True)

    events: fields.ManyToManyRelation[Event]

    class Meta:
        schema = "test_schema"
        indexes = [("alias", "name"), ["id", "name"]]

    def __str__(self):
        return self.name
