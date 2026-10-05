"""
Phase 6 Step 4
Live EntityResolver verification against the configured SQL Server database.

This is a diagnostic test only.
It does not modify the database and does not execute business queries.
"""

from app.database.entity_resolver import EntityResolver
from app.database.metadata_service import DatabaseMetadataService


def main() -> None:
    print()
    print("=" * 70)
    print("PHASE 6 - ENTITY RESOLVER LIVE TEST")
    print("=" * 70)

    metadata_service = DatabaseMetadataService()
    metadata = metadata_service.load()

    schema = metadata.schema

    print(f"Database : {metadata.database_name}")
    print(f"Server   : {metadata.server_name}")
    print(f"Tables   : {len(schema.tables)}")
    print()

    resolver = EntityResolver(schema)

    test_phrases = [
        "events",
        "sites",
        "users",
        "event name",
        "site name",
    ]

    for phrase in test_phrases:
        print("-" * 70)
        print(f"ENTITY: {phrase}")

        result = resolver.resolve(
            phrase,
            limit=5,
        )

        if not result.candidates:
            print("No candidates found.")
            print(f"Confident: {result.confident}")
            continue

        print(f"Confident: {result.confident}")
        print("Candidates:")

        for index, candidate in enumerate(
            result.candidates,
            start=1,
        ):
            print(
                f"  {index}. "
                f"{candidate.schema_name}."
                f"{candidate.table_name} "
                f"(score={candidate.score:g})"
            )

            for evidence in candidate.evidence:
                print(f"       - {evidence}")

    print()
    print("=" * 70)
    print("LIVE ENTITY RESOLVER TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()