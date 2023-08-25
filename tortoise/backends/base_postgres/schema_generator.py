from typing import TYPE_CHECKING, Any, List, Set, Type, cast

from pypika import Table
from tortoise.fields import JSONField, TextField, UUIDField
from tortoise.indexes import Index

if TYPE_CHECKING:  # pragma: nocoverage
    from tortoise.fields.relational import ForeignKeyFieldInstance  # noqa
    from tortoise.models import Model
from tortoise.backends.base.schema_generator import BaseSchemaGenerator
from tortoise.converters import encoders
from tortoise.exceptions import ConfigurationError

if TYPE_CHECKING:  # pragma: nocoverage
    from .client import BasePostgresClient
    from tortoise.fields.relational import ForeignKeyFieldInstance  # noqa
    from tortoise.models import Model


class BasePostgresSchemaGenerator(BaseSchemaGenerator):
    IF_NOT_EXISTS = "IF NOT EXISTS "
    DIALECT = "postgres"
    SCHEMA_CREATION_TEMPLATE = 'CREATE SCHEMA {exists}"{schema_name}";'

    # table name consists of the schema name and the table name separated by a '.' character.
    # fmt: off
    TABLE_CREATE_TEMPLATE = 'CREATE TABLE {exists}{table_name} ({fields}){extra}{comment};'

    TABLE_COMMENT_TEMPLATE = 'COMMENT ON TABLE {table_name} IS \'{comment}\';'
    COLUMN_COMMENT_TEMPLATE = 'COMMENT ON COLUMN {table_name}."{column}" IS \'{comment}\';'

    FIELD_TEMPLATE = '"{name}" {type} {nullable} {unique}{primary}{default}{comment}'

    GENERATED_PK_TEMPLATE = '"{field_name}" {generated_sql}'
    INDEX_CREATE_TEMPLATE = 'CREATE INDEX {exists}"{index_name}" ON {table_name} ({fields});'
    UNIQUE_CONSTRAINT_CREATE_TEMPLATE = 'CONSTRAINT "{index_name}" UNIQUE ({fields})'
    FK_TEMPLATE = ' REFERENCES {table_name} ("{field}") ON DELETE {on_delete}{comment}'

    M2M_TABLE_TEMPLATE = (
        'CREATE TABLE {exists}{table_name} (\n'
        '    "{backward_key}" {backward_type} NOT NULL{backward_fk},\n'
        '    "{forward_key}" {forward_type} NOT NULL{forward_fk}\n'
        "){extra}{comment};"
    )
    # fmt: on

    def __init__(self, client: "BasePostgresClient") -> None:
        super().__init__(client)
        self.comments_array: List[str] = []
        self.schema_names: Set[str] = set()

    def _create_fk_string(
        self,
        constraint_name: str,
        db_column: str,
        table: str,
        field: str,
        on_delete: str,
        comment: str,
    ) -> str:
        return self.FK_TEMPLATE.format(
            db_column=db_column, table_name=table, field=field, on_delete=on_delete, comment=comment
        )

    @classmethod
    def _get_escape_translation_table(cls) -> List[str]:
        table = super()._get_escape_translation_table()
        table[ord("'")] = "''"
        return table

    def _get_index_sql(self, model: "Type[Model]", field_names: List[str], safe: bool) -> str:
        return self.INDEX_CREATE_TEMPLATE.format(
            exists=self.IF_NOT_EXISTS if safe else "",
            index_name=self._generate_index_name("idx", model, field_names),
            table_name=BasePostgresSchemaGenerator._get_table_name_sql_string(model=model),
            fields=", ".join([self.quote(f) for f in field_names]),
        )

    def _table_comment_generator(self, table_name: str, comment: str) -> str:
        comment = self.TABLE_COMMENT_TEMPLATE.format(
            table_name=table_name,
            comment=self._escape_comment(comment),
        )
        self.comments_array.append(comment)
        return ""

    def _column_comment_generator(self, table: str, column: str, comment: str) -> str:
        comment = self.COLUMN_COMMENT_TEMPLATE.format(
            table_name=table, column=column, comment=self._escape_comment(comment)
        )
        if comment not in self.comments_array:
            self.comments_array.append(comment)
        return ""

    def _post_table_hook(self) -> str:
        val = "\n".join(self.comments_array)
        self.comments_array = []
        if val:
            return "\n" + val
        return ""

    def _column_default_generator(
        self,
        table: str,
        column: str,
        default: Any,
        auto_now_add: bool = False,
        auto_now: bool = False,
    ) -> str:
        default_str = " DEFAULT"
        default_str += " CURRENT_TIMESTAMP" if auto_now_add else f" {default}"
        return default_str

    def _escape_default_value(self, default: Any):
        if isinstance(default, bool):
            return default
        return encoders.get(type(default))(default)  # type: ignore

    @staticmethod
    def _get_table_name_sql_string(model: "Type[Model]") -> str:
        if isinstance(model, str):
            pass
        return (
            f'"{model._meta.schema}"."{model._meta.db_table}"'
            if model._meta.schema is not None
            else f'"{model._meta.db_table}"'
        )

    def _get_table_sql(self, model: "Type[Model]", safe: bool = True) -> dict:
        fields_to_create = []
        fields_with_index = []
        m2m_tables_for_create = []
        references = set()
        models_to_create: "List[Type[Model]]" = []

        self._get_models_to_create(models_to_create)
        models_tables = [model._meta.db_table for model in models_to_create]
        for field_name, column_name in model._meta.fields_db_projection.items():
            field_object = model._meta.fields_map[field_name]
            comment = (
                self._column_comment_generator(
                    table=BasePostgresSchemaGenerator._get_table_name_sql_string(model=model),
                    column=column_name,
                    comment=field_object.description,
                )
                if field_object.description
                else ""
            )

            default = field_object.default
            auto_now_add = getattr(field_object, "auto_now_add", False)
            auto_now = getattr(field_object, "auto_now", False)
            if default is not None or auto_now or auto_now_add:
                if callable(default) or isinstance(field_object, (UUIDField, TextField, JSONField)):
                    default = ""
                else:
                    default = field_object.to_db_value(default, model)
                    try:
                        default = self._column_default_generator(
                            model._meta.db_table,
                            column_name,
                            self._escape_default_value(default),
                            auto_now_add,
                            auto_now,
                        )
                    except NotImplementedError:
                        default = ""
            else:
                default = ""

            # TODO: PK generation needs to move out of schema generator.
            if field_object.pk:
                if field_object.generated:
                    generated_sql = field_object.get_for_dialect(self.DIALECT, "GENERATED_SQL")
                    if generated_sql:  # pragma: nobranch
                        fields_to_create.append(
                            self.GENERATED_PK_TEMPLATE.format(
                                field_name=column_name,
                                generated_sql=generated_sql,
                                comment=comment,
                            )
                        )
                        continue

            nullable = "NOT NULL" if not field_object.null else ""
            unique = "UNIQUE" if field_object.unique else ""

            if getattr(field_object, "reference", None):
                reference = cast("ForeignKeyFieldInstance", field_object.reference)
                comment = (
                    self._column_comment_generator(
                        table=BasePostgresSchemaGenerator._get_table_name_sql_string(model=model),
                        column=column_name,
                        comment=reference.description,
                    )
                    if reference.description
                    else ""
                )

                to_field_name = reference.to_field_instance.source_field
                if not to_field_name:
                    to_field_name = reference.to_field_instance.model_field_name

                field_creation_string = self._create_string(
                    db_column=column_name,
                    field_type=field_object.get_for_dialect(self.DIALECT, "SQL_TYPE"),
                    nullable=nullable,
                    unique=unique,
                    is_primary_key=field_object.pk,
                    comment="",
                    default=default,
                ) + (
                    self._create_fk_string(
                        constraint_name=self._generate_fk_name(
                            model._meta.db_table,
                            column_name,
                            reference.related_model._meta.db_table,
                            to_field_name,
                        ),
                        db_column=column_name,
                        table=BasePostgresSchemaGenerator._get_table_name_sql_string(
                            model=reference.related_model
                        ),
                        field=to_field_name,
                        on_delete=reference.on_delete,
                        comment=comment,
                    )
                    if reference.db_constraint
                    else ""
                )
                references.add(reference.related_model._meta.db_table)
            else:
                field_creation_string = self._create_string(
                    db_column=column_name,
                    field_type=field_object.get_for_dialect(self.DIALECT, "SQL_TYPE"),
                    nullable=nullable,
                    unique=unique,
                    is_primary_key=field_object.pk,
                    comment=comment,
                    default=default,
                )

            fields_to_create.append(field_creation_string)

            if field_object.index and not field_object.pk:
                fields_with_index.append(column_name)

        if model._meta.unique_together:
            for unique_together_list in model._meta.unique_together:
                unique_together_to_create = []

                for field in unique_together_list:
                    field_object = model._meta.fields_map[field]
                    unique_together_to_create.append(field_object.source_field or field)

                fields_to_create.append(
                    self._get_unique_constraint_sql(model, unique_together_to_create)
                )

        # Indexes.
        _indexes = [
            self._get_index_sql(model, [field_name], safe=safe) for field_name in fields_with_index
        ]

        if model._meta.indexes:
            for indexes_list in model._meta.indexes:
                if not isinstance(indexes_list, Index):
                    indexes_to_create = []
                    for field in indexes_list:
                        field_object = model._meta.fields_map[field]
                        indexes_to_create.append(field_object.source_field or field)

                    _indexes.append(self._get_index_sql(model, indexes_to_create, safe=safe))
                else:
                    _indexes.append(indexes_list.get_sql(self, model, safe))

        field_indexes_sqls = [val for val in list(dict.fromkeys(_indexes)) if val]

        fields_to_create.extend(self._get_inner_statements())

        table_fields_string = "\n    {}\n".format(",\n    ".join(fields_to_create))
        table_comment = (
            self._table_comment_generator(
                table_name=BasePostgresSchemaGenerator._get_table_name_sql_string(model=model),
                comment=model._meta.table_description,
            )
            if model._meta.table_description
            else ""
        )

        table_create_string = self.TABLE_CREATE_TEMPLATE.format(
            exists=self.IF_NOT_EXISTS if safe else "",
            table_name=BasePostgresSchemaGenerator._get_table_name_sql_string(model=model),
            fields=table_fields_string,
            comment=table_comment,
            extra=self._table_generate_extra(
                table=BasePostgresSchemaGenerator._get_table_name_sql_string(model=model)
            ),
        )

        table_create_string = "\n".join([table_create_string, *field_indexes_sqls])

        table_create_string += self._post_table_hook()

        for m2m_field in model._meta.m2m_fields:
            field_object = cast("ManyToManyFieldInstance", model._meta.fields_map[m2m_field])
            if field_object._generated or field_object.through in models_tables:
                continue

            through_table: str = str(Table(name=field_object.through, schema=model._meta.schema))

            m2m_create_string = self.M2M_TABLE_TEMPLATE.format(
                exists=self.IF_NOT_EXISTS if safe else "",
                table_name=through_table,
                backward_fk=self._create_fk_string(
                    constraint_name="",
                    db_column=field_object.backward_key,
                    table=BasePostgresSchemaGenerator._get_table_name_sql_string(model=model),
                    field=model._meta.db_pk_column,
                    on_delete=field_object.on_delete,
                    comment="",
                )
                if field_object.db_constraint
                else "",
                forward_fk=self._create_fk_string(
                    constraint_name="",
                    db_column=field_object.forward_key,
                    table=BasePostgresSchemaGenerator._get_table_name_sql_string(
                        model=field_object.related_model
                    ),
                    field=field_object.related_model._meta.db_pk_column,
                    on_delete=field_object.on_delete,
                    comment="",
                )
                if field_object.db_constraint
                else "",
                backward_key=field_object.backward_key,
                backward_type=model._meta.pk.get_for_dialect(self.DIALECT, "SQL_TYPE"),
                forward_key=field_object.forward_key,
                forward_type=field_object.related_model._meta.pk.get_for_dialect(
                    self.DIALECT, "SQL_TYPE"
                ),
                extra=self._table_generate_extra(table=through_table),
                comment=self._table_comment_generator(
                    table_name=through_table,
                    comment=field_object.description,
                )
                if field_object.description
                else "",
            )
            if not field_object.db_constraint:
                m2m_create_string = m2m_create_string.replace(
                    """,
    ,
    """,
                    "",
                )  # may have better way
            m2m_create_string += self._post_table_hook()
            m2m_tables_for_create.append(m2m_create_string)

        return {
            "table": model._meta.db_table,
            "schema": model._meta.schema,
            "model": model,
            "table_creation_string": table_create_string,
            "references": references,
            "m2m_tables": m2m_tables_for_create,
        }

    def get_create_schema_sql(self, safe: bool = True) -> str:
        models_to_create: "List[Type[Model]]" = []
        self._get_models_to_create(models_to_create)

        tables_to_create: list[dict] = []
        for model in models_to_create:
            if model._meta.schema is not None:
                self.schema_names.add(model._meta.schema)
            tables_to_create.append(self._get_table_sql(model, safe))

        create_schemas_sql = [
            self.SCHEMA_CREATION_TEMPLATE.format(
                exists=self.IF_NOT_EXISTS if safe else "", schema_name=schema_name
            )
            for schema_name in self.schema_names
            if schema_name is not "public"
        ]

        tables_to_create_count = len(tables_to_create)

        created_tables: Set[dict] = set()
        ordered_tables_for_create: List[str] = []
        m2m_tables_to_create: List[str] = []
        while True:
            if len(created_tables) == tables_to_create_count:
                break
            try:
                next_table_for_create = next(
                    t
                    for t in tables_to_create
                    if t["references"].issubset(created_tables | {t["table"]})
                )
            except StopIteration:
                raise ConfigurationError("Can't create schema due to cyclic fk references")
            tables_to_create.remove(next_table_for_create)
            created_tables.add(next_table_for_create["table"])
            ordered_tables_for_create.append(next_table_for_create["table_creation_string"])
            m2m_tables_to_create += next_table_for_create["m2m_tables"]

        schema_creation_string = "\n".join(
            create_schemas_sql + ordered_tables_for_create + m2m_tables_to_create
        )
        return schema_creation_string
