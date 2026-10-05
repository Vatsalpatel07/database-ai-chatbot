from app.database.entity_resolver import EntityResolver
from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    TableInfo,
)


def column(
    name: str,
    data_type: str = "nvarchar",
    nullable: bool = True,
    ordinal_position: int = 1,
) -> ColumnInfo:
    return ColumnInfo(
        name=name,
        data_type=data_type,
        nullable=nullable,
        ordinal_position=ordinal_position,
    )


def build_schema() -> DatabaseSchema:
    return DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="customers",
                columns=[
                    column(
                        "customer_id",
                        "int",
                        False,
                        1,
                    ),
                    column(
                        "customer_name",
                        "nvarchar",
                        False,
                        2,
                    ),
                    column(
                        "email",
                        "nvarchar",
                        True,
                        3,
                    ),
                    column(
                        "status",
                        "nvarchar",
                        True,
                        4,
                    ),
                ],
                primary_key_columns=["customer_id"],
            ),
            TableInfo(
                schema_name="dbo",
                table_name="orders",
                columns=[
                    column(
                        "order_id",
                        "int",
                        False,
                        1,
                    ),
                    column(
                        "order_date",
                        "datetime",
                        False,
                        2,
                    ),
                    column(
                        "order_status",
                        "nvarchar",
                        True,
                        3,
                    ),
                    column(
                        "customer_id",
                        "int",
                        False,
                        4,
                    ),
                ],
                primary_key_columns=["order_id"],
            ),
            TableInfo(
                schema_name="dbo",
                table_name="order_items",
                columns=[
                    column(
                        "order_item_id",
                        "int",
                        False,
                        1,
                    ),
                    column(
                        "order_id",
                        "int",
                        False,
                        2,
                    ),
                    column(
                        "product_name",
                        "nvarchar",
                        True,
                        3,
                    ),
                    column(
                        "quantity",
                        "int",
                        False,
                        4,
                    ),
                ],
                primary_key_columns=["order_item_id"],
            ),
            TableInfo(
                schema_name="dbo",
                table_name="customer_addresses",
                columns=[
                    column(
                        "address_id",
                        "int",
                        False,
                        1,
                    ),
                    column(
                        "customer_id",
                        "int",
                        False,
                        2,
                    ),
                    column(
                        "address_name",
                        "nvarchar",
                        True,
                        3,
                    ),
                ],
                primary_key_columns=["address_id"],
            ),
        ],
        foreign_keys=[],
        unique_constraints=[],
    )


def test_exact_table_name():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("customers")

    assert result.candidates
    assert result.candidates[0].table_name == "customers"


def test_plural_entity():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("orders")

    assert result.candidates
    assert result.candidates[0].table_name == "orders"


def test_column_phrase():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("email")

    assert result.candidates
    assert any(
        candidate.table_name == "customers"
        for candidate in result.candidates
    )


def test_unknown_entity():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("airports")

    assert result.candidates == []
    assert result.confident is False


def test_limit():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve(
        "name",
        limit=2,
    )

    assert len(result.candidates) <= 2


def test_many_column_matches_do_not_overwhelm_table_match():
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="orders",
                columns=[
                    column(
                        "order_id",
                        "int",
                        False,
                        1,
                    ),
                    column(
                        "customer_name",
                        "nvarchar",
                        True,
                        2,
                    ),
                    column(
                        "product_name",
                        "nvarchar",
                        True,
                        3,
                    ),
                    column(
                        "shipping_name",
                        "nvarchar",
                        True,
                        4,
                    ),
                    column(
                        "billing_name",
                        "nvarchar",
                        True,
                        5,
                    ),
                ],
                primary_key_columns=["order_id"],
            ),
            TableInfo(
                schema_name="dbo",
                table_name="customer_profiles",
                columns=[
                    column(
                        "customer_id",
                        "int",
                        False,
                        1,
                    ),
                ],
                primary_key_columns=["customer_id"],
            ),
        ],
        foreign_keys=[],
        unique_constraints=[],
    )

    resolver = EntityResolver(schema)

    result = resolver.resolve("orders")

    assert result.candidates
    assert result.candidates[0].table_name == "orders"


def test_ambiguous_candidates_are_not_confident():
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="customer_accounts",
                columns=[
                    column(
                        "customer_id",
                        "int",
                        False,
                        1,
                    ),
                    column(
                        "customer_name",
                        "nvarchar",
                        True,
                        2,
                    ),
                ],
                primary_key_columns=["customer_id"],
            ),
            TableInfo(
                schema_name="dbo",
                table_name="customer_profiles",
                columns=[
                    column(
                        "customer_id",
                        "int",
                        False,
                        1,
                    ),
                    column(
                        "customer_name",
                        "nvarchar",
                        True,
                        2,
                    ),
                ],
                primary_key_columns=["customer_id"],
            ),
        ],
        foreign_keys=[],
        unique_constraints=[],
    )

    resolver = EntityResolver(schema)

    result = resolver.resolve("customer")

    assert result.candidates
    assert result.confident is False


# ----------------------------------------------------------------------
# Phase 6 Step 6 — Compound phrase tests
# ----------------------------------------------------------------------


def test_compound_entity_attribute_prefers_matching_entity_table():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("order date")

    assert result.candidates
    assert result.candidates[0].table_name == "orders"


def test_compound_entity_attribute_prefers_customer_name_table():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("customer name")

    assert result.candidates
    assert result.candidates[0].table_name == "customers"


def test_compound_entity_attribute_supports_status():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("order status")

    assert result.candidates
    assert result.candidates[0].table_name == "orders"


def test_compound_attribute_requires_entity_evidence():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("name")

    assert result.candidates
    assert result.confident is False


def test_compound_phrase_exposes_entity_and_attribute_evidence():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("customer name")

    assert result.candidates

    top = result.candidates[0]

    assert top.table_name == "customers"

    evidence_text = " ".join(
        top.evidence
    ).lower()

    assert "compound entity match" in evidence_text
    assert "compound attribute match" in evidence_text


def test_compound_phrase_does_not_use_generic_attribute_alone():
    resolver = EntityResolver(build_schema())

    result = resolver.resolve("status")

    assert result.candidates
    assert result.confident is False