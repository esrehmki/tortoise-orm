from tortoise import Model, fields


class NonPublicSchemaModel(Model):
    name = fields.TextField()

    class Meta:
        table = "non_public_schema_model"
        schema = "non_public"
