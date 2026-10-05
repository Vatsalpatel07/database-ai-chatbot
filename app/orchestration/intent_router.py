from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DatabaseRoute:
    """
    Generic routing decision for a database question.

    The route determines which application-level processing path
    should handle the question.

    It does not interpret business-specific entities, tables,
    columns, or values.
    """

    name: str


class DatabaseIntentRouter:
    """
    Deterministic application-level intent router.

    Phase 5 responsibilities:
      - identify database-scope requests that can be handled
        without the general query planner
      - identify ambiguous database-level requests
      - route all other questions to the normal query pipeline

    This component does NOT:
      - select tables
      - generate SQL
      - call DeepSeek
      - validate QueryPlans
      - discover relationships
      - execute queries

    Those responsibilities remain in their existing components.
    """

    ROUTE_QUERY = "query"
    ROUTE_DATABASE_METADATA = "database_metadata"
    ROUTE_RELATIONSHIP_METADATA = "relationship_metadata"
    ROUTE_DATABASE_ROW_STATISTICS = "database_row_statistics"
    ROUTE_AMBIGUOUS_ROW_COUNT = "ambiguous_row_count"

    def route(self, question: str) -> DatabaseRoute:
        """
        Return the application-level route for a database question.
        """

        question = (question or "").strip()

        if not question:
            raise ValueError("Question cannot be empty.")

        if self.is_relationship_metadata_request(question):
            return DatabaseRoute(
                name=self.ROUTE_RELATIONSHIP_METADATA
            )

        if self.is_database_row_statistics_request(question):
            return DatabaseRoute(
                name=self.ROUTE_DATABASE_ROW_STATISTICS
            )

        if self.is_ambiguous_row_count_request(question):
            return DatabaseRoute(
                name=self.ROUTE_AMBIGUOUS_ROW_COUNT
            )

        if self.is_database_metadata_request(question):
            return DatabaseRoute(
                name=self.ROUTE_DATABASE_METADATA
            )

        return DatabaseRoute(
            name=self.ROUTE_QUERY
        )

    # ==========================================================
    # DATABASE METADATA
    # ==========================================================

    @classmethod
    def is_database_metadata_request(
        cls,
        question: str,
    ) -> bool:
        """
        Detect generic requests for database table names.

        This is intentionally independent of any business schema.
        """

        text = cls._normalize(question)

        patterns = [
            r"\bhow\s+many\s+tables?\s+(?:are\s+there|exist|are\s+in\s+(?:the\s+)?database|do\s+we\s+have|are\s+available)\b",
            r"\bshow\s+(?:me\s+)?(?:all\s+)?tables?\b",
            r"\blist\s+(?:all\s+)?tables?\b",
            (
                r"\bwhat\s+tables?\s+(?:are\s+)?"
                r"(?:available|there|in\s+the\s+database)\b"
            ),
            r"\bwhich\s+tables?\s+(?:exist|are\s+available)\b",
            r"\btable\s+names?\b",
            r"\blist\s+(?:the\s+)?table\s+names?\b",
        ]

        return cls._matches_any(text, patterns)

    # ==========================================================
    # RELATIONSHIP METADATA
    # ==========================================================

    @classmethod
    def is_relationship_metadata_request(
        cls,
        question: str,
    ) -> bool:
        """
        Detect generic database relationship questions.
        """

        text = cls._normalize(question)

        patterns = [
            r"\b(?:which|what)\s+tables?\s+(?:are\s+)?related\b",
            (
                r"\b(?:show|list|display|give|return)\s+"
                r"(?:me\s+)?(?:the\s+)?(?:table\s+)?"
                r"relationships\b"
            ),
            (
                r"\b(?:show|list|display|give|return)\s+"
                r"(?:me\s+)?(?:all\s+)?relationships\s+"
                r"(?:between|among)\s+(?:the\s+)?tables?\b"
            ),
            (
                r"\bhow\s+(?:are|is)\s+(?:the\s+)?tables?\s+"
                r"(?:related|connected)\b"
            ),
            r"\bhow\s+(?:are|is)\s+(?:the\s+)?tables?\s+connected\b",
            (
                r"\b(?:what|which)\s+(?:table\s+)?relationships\s+"
                r"(?:exist|are\s+there)\b"
            ),
            (
                r"\bshow\s+(?:me\s+)?(?:the\s+)?"
                r"(?:database\s+)?relationships\b"
            ),
        ]

        return cls._matches_any(text, patterns)

    # ==========================================================
    # DATABASE-WIDE ROW STATISTICS
    # ==========================================================

    @classmethod
    def is_database_row_statistics_request(
        cls,
        question: str,
    ) -> bool:
        """
        Detect explicit requests for row counts across all tables.
        """

        text = cls._normalize(question)

        patterns = [
            (
                r"\bhow\s+many\s+rows?\s+"
                r"(?:are\s+there|are\s+in)\s+"
                r"(?:across|throughout)\s+"
                r"(?:all\s+)?(?:the\s+)?tables?\b"
            ),
            (
                r"\bhow\s+many\s+records?\s+"
                r"(?:are\s+there|are\s+in)\s+"
                r"(?:across|throughout)\s+"
                r"(?:all\s+)?(?:the\s+)?tables?\b"
            ),
            (
                r"\bhow\s+many\s+rows?\s+"
                r"(?:are\s+there|are\s+in)\s+"
                r"(?:the\s+)?"
                r"(?:entire|whole|complete)\s+database\b"
            ),
            (
                r"\bhow\s+many\s+records?\s+"
                r"(?:are\s+there|are\s+in)\s+"
                r"(?:the\s+)?"
                r"(?:entire|whole|complete)\s+database\b"
            ),
            (
                r"\bhow\s+many\s+rows?\s+"
                r"(?:are\s+there|are\s+in)\s+"
                r"(?:the\s+)?database\b"
            ),
            (
                r"\bhow\s+many\s+records?\s+"
                r"(?:are\s+there|are\s+in)\s+"
                r"(?:the\s+)?database\b"
            ),
            (
                r"\b(?:give|show|list|display|return)\s+"
                r"(?:me\s+)?(?:the\s+)?row\s+counts?\s+"
                r"(?:for|of)\s+(?:all|every)\s+tables?\b"
            ),
            (
                r"\b(?:give|show|list|display|return)\s+"
                r"(?:me\s+)?(?:the\s+)?record\s+counts?\s+"
                r"(?:for|of)\s+(?:all|every)\s+tables?\b"
            ),
            r"\brow\s+counts?\s+(?:for|of)\s+(?:all|every)\s+tables?\b",
            (
                r"\brecord\s+counts?\s+(?:for|of)\s+"
                r"(?:all|every)\s+tables?\b"
            ),
        ]

        return cls._matches_any(text, patterns)

    # ==========================================================
    # AMBIGUOUS ROW COUNT
    # ==========================================================

    @classmethod
    def is_ambiguous_row_count_request(
        cls,
        question: str,
    ) -> bool:
        """
        Detect row-count questions that do not identify a table.

        These questions must not be routed to an arbitrary table.
        """

        text = cls._normalize(question)

        patterns = [
            (
                r"^how\s+many\s+rows?\s+"
                r"(?:are\s+there|is\s+there)\s*\??$"
            ),
            (
                r"^how\s+many\s+records?\s+"
                r"(?:are\s+there|is\s+there)\s*\??$"
            ),
            (
                r"^what\s+is\s+the\s+"
                r"(?:total\s+)?(?:row|record)\s+count\s*\??$"
            ),
            (
                r"^how\s+many\s+records?\s+"
                r"are\s+in\s+the\s+database\s*\??$"
            ),
            (
                r"^how\s+many\s+rows?\s+"
                r"are\s+in\s+the\s+database\s*\??$"
            ),
        ]

        return cls._matches_any(text, patterns)

    # ==========================================================
    # HELPERS
    # ==========================================================

    @staticmethod
    def _normalize(question: str) -> str:
        """
        Normalize whitespace and case without changing semantics.
        """

        return re.sub(
            r"\s+",
            " ",
            (question or "").strip().casefold(),
        )

    @staticmethod
    def _matches_any(
        text: str,
        patterns: list[str],
    ) -> bool:
        return any(
            re.search(pattern, text)
            for pattern in patterns
        )