from __future__ import annotations

from typing import Any
import re

from app.database.connection import get_connection
from app.database.metadata_service import DatabaseMetadataService
from app.database.query_service import (
    DatabaseQueryResult,
    DatabaseQueryService,
)
from app.database.relationship_service import RelationshipDiscoveryService
from app.database.schema import DatabaseSchema
from app.query.schema import QueryPlan
from app.orchestration.intent_router import DatabaseIntentRouter


class DatabaseOrchestrationError(Exception):
    """Raised when the application orchestration layer fails."""


class DatabaseOrchestrator:
    """
    Application-level coordinator for database questions.

    Phase 5 responsibilities:
      - load database metadata
      - determine the application-level route
      - handle deterministic database-scope routes
      - delegate normal data questions to DatabaseQueryService
      - expose the current schema to the API layer

    Business-specific table and column names are never hardcoded here.
    """

    def __init__(
        self,
        schema: DatabaseSchema | None = None,
        query_service: DatabaseQueryService | None = None,
        metadata_service: DatabaseMetadataService | None = None,
        intent_router: DatabaseIntentRouter | None = None,
        relationship_service: RelationshipDiscoveryService | None = None,
    ) -> None:
        self._schema = schema
        self._query_service = query_service
        self._metadata_service = (
            metadata_service or DatabaseMetadataService()
        )
        self._intent_router = (
            intent_router or DatabaseIntentRouter()
        )
        self._relationship_service = relationship_service
        self._metadata = None

    # ==========================================================
    # METADATA
    # ==========================================================

    @property
    def metadata(self):
        """Load the current database metadata lazily."""

        if self._metadata is None:
            try:
                self._metadata = self._metadata_service.load()
            except Exception as exc:
                raise DatabaseOrchestrationError(
                    str(exc)
                ) from exc

        return self._metadata

    @property
    def schema(self) -> DatabaseSchema:
        """Expose the structural database schema."""

        if self._schema is None:
            self._schema = self.metadata.schema

        if not self._schema.tables:
            raise DatabaseOrchestrationError(
                "The configured database contains no tables."
            )

        return self._schema

    @property
    def relationship_service(self) -> RelationshipDiscoveryService:
        """Expose the canonical Phase 5 relationship service."""

        if self._relationship_service is None:
            self._relationship_service = RelationshipDiscoveryService(
                database_schema=self.schema,
                server_name=self.metadata.server_name,
                database_name=self.metadata.database_name,
                schema_fingerprint=self.metadata.schema_fingerprint,
            )

        return self._relationship_service

    @property
    def query_service(self) -> DatabaseQueryService:
        """Create the normal query service lazily."""

        if self._query_service is None:
            self._query_service = DatabaseQueryService(
                database_schema=self.schema,
                relationship_service=self.relationship_service,
                metadata_service=self._metadata_service,
            )

        return self._query_service

    @property
    def intent_router(self) -> DatabaseIntentRouter:
        """Expose the Phase 5 intent router."""

        return self._intent_router

    # ==========================================================
    # ROUTING
    # ==========================================================

    def route(self, question: str) -> str:
        """
        Determine the application-level route.

        Routing itself is deterministic and does not call DeepSeek.
        """

        question = (question or "").strip()

        if not question:
            raise DatabaseOrchestrationError(
                "Question cannot be empty."
            )

        try:
            route = self._intent_router.route(question)
        except Exception as exc:
            raise DatabaseOrchestrationError(
                f"Intent routing failed: {exc}"
            ) from exc

        return route.name

    # ==========================================================
    # DETERMINISTIC ROUTE HANDLERS
    # ==========================================================

    def _handle_database_metadata_request(
        self,
    ) -> DatabaseQueryResult:
        """
        Return database table names directly from discovered metadata.
        """

        return DatabaseQueryResult(
            plan=QueryPlan(
                intent="column_names",
                explanation="List the available database tables.",
                confidence=1.0,
            ),
            data=[
                f"{table.schema_name}.{table.table_name}"
                for table in self.schema.tables
            ],
            warnings=[],
        )

    def _handle_relationship_metadata_request(
        self,
    ) -> DatabaseQueryResult:
        """
        Return structurally/data-validated relationships.

        Relationship discovery remains generic and is delegated to
        RelationshipDiscoveryService.
        """

        selected_table_keys = [
            (
                table.schema_name,
                table.table_name,
            )
            for table in self.schema.tables
        ]

        if len(selected_table_keys) < 2:
            relationships: list[dict[str, Any]] = []
        else:
            discovered = self.relationship_service.discover(
                selected_table_keys
            )

            relationships = []

            for relationship in discovered:
                if relationship.status not in {
                    "confirmed",
                    "validated",
                    "candidate_validated",
                }:
                    continue

                relationships.append(
                    {
                        "relationship_type": (
                            relationship.relationship_type
                        ),
                        "status": relationship.status,
                        "left_schema": relationship.left_schema,
                        "left_table": relationship.left_table,
                        "left_column": relationship.left_column,
                        "right_schema": relationship.right_schema,
                        "right_table": relationship.right_table,
                        "right_column": relationship.right_column,
                        "reason": relationship.reason,
                    }
                )

        return DatabaseQueryResult(
            plan=QueryPlan(
                intent="lookup",
                explanation=(
                    "Return structurally discovered relationships "
                    "between database tables."
                ),
                confidence=1.0,
            ),
            data=relationships,
            warnings=[],
        )

    def _handle_database_row_statistics_request(
        self,
    ) -> DatabaseQueryResult:
        """
        Return live row counts for every discovered table.

        Counts are executed against SQL Server at request time.
        """

        results: list[dict[str, Any]] = []

        from app.core.config import DatabaseConfig
        is_postgresql = DatabaseConfig.from_env().is_postgresql

        with get_connection() as connection:
            cursor = connection.cursor()

            for table in self.schema.tables:
                schema_name = re.sub(
                    r"[^\w]",
                    "",
                    table.schema_name,
                )

                table_name = re.sub(
                    r"[^\w]",
                    "",
                    table.table_name,
                )

                if not schema_name or not table_name:
                    continue

                quoted_schema = f'"{schema_name}"' if is_postgresql else f"[{schema_name}]"
                quoted_table = f'"{table_name}"' if is_postgresql else f"[{table_name}]"

                cursor.execute(
                    f"SELECT COUNT(*) AS row_count "
                    f"FROM {quoted_schema}.{quoted_table}"
                )

                row = cursor.fetchone()

                count_val = getattr(row, "row_count", None)
                if count_val is None:
                    count_val = row[0]

                results.append(
                    {
                        "schema": table.schema_name,
                        "table": table.table_name,
                        "row_count": int(count_val),
                    }
                )

        return DatabaseQueryResult(
            plan=QueryPlan(
                intent="row_count",
                explanation=(
                    "Return row counts for all available "
                    "database tables."
                ),
                confidence=1.0,
            ),
            data=results,
            warnings=[],
        )

    def _handle_ambiguous_row_count_request(
        self,
    ) -> DatabaseQueryResult:
        """
        Do not guess a table when a row-count question has no
        identifiable table.
        """

        return DatabaseQueryResult(
            plan=QueryPlan(
                intent="row_count",
                explanation=(
                    "The question does not identify a specific table. "
                    "Ask the user to specify which table they want "
                    "the row count for."
                ),
                confidence=1.0,
            ),
            data=[],
            warnings=[
                (
                    "The database contains multiple tables. "
                    "Please specify which table you want "
                    "the row count for."
                )
            ],
        )

    # ==========================================================
    # REFRESH
    # ==========================================================

    def refresh_metadata(self):
        """Explicitly reload database metadata."""

        try:
            self._metadata = self._metadata_service.load()
        except Exception as exc:
            raise DatabaseOrchestrationError(
                str(exc)
            ) from exc

        self._schema = self._metadata.schema

        self._query_service = DatabaseQueryService(
            database_schema=self._schema,
        )

        return self._metadata

    def refresh_schema(self) -> DatabaseSchema:
        """Backward-compatible schema refresh."""

        return self.refresh_metadata().schema

    # ==========================================================
    # ANSWER
    # ==========================================================

    def answer(
        self,
        question: str,
        conversation_context: dict[str, Any] | None = None,
    ) -> DatabaseQueryResult:
        """
        Route and execute one database question.

        Deterministic database-scope routes are handled here and
        therefore do not enter the DeepSeek query-planning path.

        Normal data questions continue through DatabaseQueryService,
        including Phase 4 semantic query caching.
        """

        question = (question or "").strip()

        if not question:
            raise DatabaseOrchestrationError(
                "Question cannot be empty."
            )

        try:
            route_name = self.route(question)

            print(
                "\n========== DATABASE INTENT ROUTING =========="
            )
            print("QUESTION:", question)
            print("ROUTE:", route_name)
            print(
                "============================================\n"
            )

            if (
                route_name
                == DatabaseIntentRouter.ROUTE_DATABASE_METADATA
            ):
                return self._handle_database_metadata_request()

            if (
                route_name
                == DatabaseIntentRouter.ROUTE_RELATIONSHIP_METADATA
            ):
                return self._handle_relationship_metadata_request()

            if (
                route_name
                == DatabaseIntentRouter.ROUTE_DATABASE_ROW_STATISTICS
            ):
                return self._handle_database_row_statistics_request()

            if (
                route_name
                == DatabaseIntentRouter.ROUTE_AMBIGUOUS_ROW_COUNT
            ):
                return self._handle_ambiguous_row_count_request()

            # Normal data/query route.
            return self.query_service.answer(
                question=question,
                conversation_context=conversation_context,
            )

        except Exception as exc:
            if isinstance(
                exc,
                DatabaseOrchestrationError,
            ):
                raise

            raise DatabaseOrchestrationError(
                str(exc)
            ) from exc