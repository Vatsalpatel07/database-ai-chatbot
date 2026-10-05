from __future__ import annotations

from app.database.metadata_service import DatabaseMetadataService
from app.database.relationship_service import RelationshipDiscoveryService


TABLE_GROUPS = [
    [
        ("dbo", "site_details"),
        ("dbo", "site_events"),
        ("dbo", "site_details_activity_report"),
    ],
    [
        ("dbo", "site_events"),
        ("dbo", "site_event_registrants"),
        ("dbo", "site_event_leads"),
    ],
    [
        ("dbo", "site_details"),
        ("dbo", "site_project_codes"),
        ("dbo", "site_events"),
    ],
]


def run_group(
    service: RelationshipDiscoveryService,
    group_number: int,
    selected_tables: list[tuple[str, str]],
) -> None:
    print()
    print("=" * 70)
    print(f"TABLE GROUP {group_number}")
    print("=" * 70)

    for schema_name, table_name in selected_tables:
        print(f"  {schema_name}.{table_name}")

    print()
    print("-" * 70)
    print("RELATIONSHIPS")
    print("-" * 70)

    results = service.discover(selected_tables)

    if not results:
        print("No validated relationships discovered.")
        return

    for index, result in enumerate(results, start=1):
        print()
        print(
            f"{index}. "
            f"{result.left_schema}.{result.left_table}."
            f"{result.left_column}"
        )
        print(
            "   -> "
            f"{result.right_schema}.{result.right_table}."
            f"{result.right_column}"
        )
        print(
            f"   type                : "
            f"{result.relationship_type}"
        )
        print(
            f"   status              : "
            f"{result.status}"
        )
        print(
            f"   confidence          : "
            f"{result.confidence}"
        )
        print(
            f"   matching values     : "
            f"{result.matching_value_count}"
        )
        print(
            f"   left distinct       : "
            f"{result.left_distinct_count}"
        )
        print(
            f"   right distinct      : "
            f"{result.right_distinct_count}"
        )
        print(
            f"   reason              : "
            f"{result.reason}"
        )


def main() -> None:
    print()
    print("=" * 70)
    print("PHASE 7 - BROADER RELATIONSHIP COVERAGE TEST")
    print("=" * 70)

    metadata_service = DatabaseMetadataService()
    metadata = metadata_service.load()

    print(f"Database : {metadata.database_name}")
    print(f"Server   : {metadata.server_name}")
    print(f"Tables   : {len(metadata.schema.tables)}")

    service = RelationshipDiscoveryService(
        metadata.schema
    )

    for group_number, selected_tables in enumerate(
        TABLE_GROUPS,
        start=1,
    ):
        run_group(
            service,
            group_number,
            selected_tables,
        )

    print()
    print("=" * 70)
    print("BROADER RELATIONSHIP COVERAGE TEST COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()