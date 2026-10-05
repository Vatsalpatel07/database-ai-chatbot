from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from app.database.schema import DatabaseSchema, TableInfo


_STOP_WORDS = {
    "a",
    "all",
    "an",
    "and",
    "are",
    "be",
    "by",
    "can",
    "could",
    "do",
    "does",
    "for",
    "from",
    "give",
    "how",
    "i",
    "in",
    "is",
    "it",
    "list",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "the",
    "there",
    "to",
    "what",
    "which",
    "who",
    "with",
    "would",
}


_GENERIC_SYNONYMS = {
    "number": "count",
    "numbers": "count",
    "no": "count",
    "total": "count",
    "totals": "count",
    "records": "record",
    "entries": "entry",
    "rows": "row",
    "details": "detail",
    "names": "name",
    "statuses": "status",
    "states": "status",
}


@dataclass(frozen=True)
class ColumnSemanticProfile:
    """Generic semantic metadata inferred from a column identifier/type."""

    name: str
    tokens: frozenset[str]
    roles: frozenset[str]


@dataclass(frozen=True)
class TableSemanticProfile:
    """Compact semantic profile used for deterministic schema routing."""

    schema_name: str
    table_name: str
    table_tokens: frozenset[str]
    entity_tokens: frozenset[str]
    columns: tuple[ColumnSemanticProfile, ...]


class DatabaseSchemaIntelligence:
    """
    Deterministic semantic index over database metadata.

    This layer deliberately does not use an LLM and does not contain
    business-specific table/column mappings. It turns structural names
    and data types into reusable metadata that table selection can use
    before DeepSeek is called.
    """

    def __init__(self, database_schema: DatabaseSchema) -> None:
        self.database_schema = database_schema

        self._profiles: dict[
            tuple[str, str],
            TableSemanticProfile,
        ] = {
            self._table_key(table): self._build_table_profile(table)
            for table in database_schema.tables
        }

        self.schema_fingerprint = self._build_schema_fingerprint()

    @staticmethod
    def _table_key(table: TableInfo) -> tuple[str, str]:
        return table.schema_name, table.table_name

    @staticmethod
    def normalize_identifier(value: str) -> str:
        value = str(value or "")

        value = re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1 \2",
            value,
        )

        value = value.replace("_", " ")
        value = value.replace("-", " ")

        value = re.sub(
            r"[^a-zA-Z0-9\s]",
            " ",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip().lower()

        return value

    @classmethod
    def tokenize(cls, value: str) -> set[str]:
        words = cls.normalize_identifier(value).split()

        tokens: set[str] = set()

        for word in words:
            if word in _STOP_WORDS or len(word) <= 1:
                continue

            tokens.add(
                _GENERIC_SYNONYMS.get(word, word)
            )

            if word.endswith("ies") and len(word) > 3:
                tokens.add(word[:-3] + "y")

            elif word.endswith("s") and not word.endswith("ss"):
                tokens.add(word[:-1])

        return tokens

    @staticmethod
    def infer_roles(
        column_name: str,
        data_type: str,
    ) -> set[str]:
        name = column_name.casefold()
        data_type = data_type.casefold()

        roles: set[str] = set()

        if (
            re.search(
                r"(^|_)(id|key|uuid|guid|identifier|code)(_|$)",
                name,
            )
            or name.endswith("_id")
            or name.endswith("id")
        ):
            roles.add("identifier")

        if re.search(
            r"(^|_)(name|title|label)(_|$)",
            name,
        ):
            roles.add("name")

        if re.search(
            r"(^|_)(description|desc|details)(_|$)",
            name,
        ):
            roles.add("description")

        if re.search(
            r"(^|_)(status|state|type|category)(_|$)",
            name,
        ):
            roles.add("category")

        if any(
            token in name
            for token in (
                "date",
                "time",
                "datetime",
                "timestamp",
            )
        ):
            roles.add("temporal")

        if data_type in {
            "bit",
            "boolean",
        }:
            roles.add("boolean")

        if data_type in {
            "tinyint",
            "smallint",
            "int",
            "bigint",
            "decimal",
            "numeric",
            "money",
            "smallmoney",
            "float",
            "real",
        }:
            roles.add("numeric")

        if data_type in {
            "date",
            "datetime",
            "datetime2",
            "smalldatetime",
            "datetimeoffset",
            "time",
        }:
            roles.add("temporal")

        return roles

    def _build_table_profile(
        self,
        table: TableInfo,
    ) -> TableSemanticProfile:
        table_tokens = self.tokenize(
            table.table_name
        )

        column_profiles: list[
            ColumnSemanticProfile
        ] = []

        entity_tokens: set[str] = set(
            table_tokens
        )

        for column in table.columns:
            tokens = self.tokenize(
                column.name
            )

            roles = self.infer_roles(
                column.name,
                column.data_type,
            )

            profile = ColumnSemanticProfile(
                name=column.name,
                tokens=frozenset(tokens),
                roles=frozenset(roles),
            )

            column_profiles.append(profile)

            # Identifier/name columns are especially useful for identifying
            # the business entity represented by a table without hardcoding it.
            if roles & {"identifier", "name"}:
                entity_tokens.update(tokens)

        return TableSemanticProfile(
            schema_name=table.schema_name,
            table_name=table.table_name,
            table_tokens=frozenset(table_tokens),
            entity_tokens=frozenset(entity_tokens),
            columns=tuple(column_profiles),
        )

    def profile_for(
        self,
        table: TableInfo,
    ) -> TableSemanticProfile:
        return self._profiles[
            self._table_key(table)
        ]

    def get_table_profile(
        self,
        schema_name: str,
        table_name: str,
    ) -> TableSemanticProfile | None:
        """
        Return the semantic profile for a schema/table pair.

        This is the public lookup used by EntityResolver.
        """
        return self._profiles.get(
            (schema_name, table_name)
        )

    def profiles(
        self,
    ) -> Iterable[TableSemanticProfile]:
        return self._profiles.values()

    def score_table(
        self,
        question: str,
        table: TableInfo,
    ) -> int:
        """Return a deterministic relevance score for a table."""

        question_tokens = self.tokenize(
            question
        )

        if not question_tokens:
            return 0

        profile = self.profile_for(table)

        score = 0

        # Exact entity/table vocabulary is the strongest signal.
        score += (
            len(
                question_tokens
                & profile.table_tokens
            )
            * 12
        )

        score += (
            len(
                question_tokens
                & profile.entity_tokens
            )
            * 7
        )

        column_score = 0
        max_column_score = 12

        for column in profile.columns:
            overlap = (
                question_tokens
                & column.tokens
            )

            if not overlap:
                continue

            weight = 3

            if "identifier" in column.roles:
                weight += 2

            if "name" in column.roles:
                weight += 2

            if "category" in column.roles:
                weight += 1

            column_score += len(overlap) * weight

        score += min(column_score, max_column_score)

        return score

    def _build_schema_fingerprint(self) -> str:
        parts: list[str] = []

        for table in sorted(
            self.database_schema.tables,
            key=self._table_key,
        ):
            parts.append(
                f"T:{table.schema_name}.{table.table_name}"
            )

            for column in sorted(
                table.columns,
                key=lambda item: item.ordinal_position,
            ):
                parts.append(
                    "C:"
                    f"{column.name}|"
                    f"{column.data_type}|"
                    f"{column.nullable}|"
                    f"{column.ordinal_position}"
                )

            parts.extend(
                f"PK:{column}"
                for column in table.primary_key_columns
            )

        parts.extend(
            "FK:"
            f"{item.schema_name}.{item.table_name}."
            f"{item.column_name}->"
            f"{item.referenced_schema_name}."
            f"{item.referenced_table_name}."
            f"{item.referenced_column_name}"
            for item in sorted(
                self.database_schema.foreign_keys,
                key=lambda item: (
                    item.schema_name,
                    item.table_name,
                    item.column_name,
                    item.referenced_schema_name,
                    item.referenced_table_name,
                    item.referenced_column_name,
                ),
            )
        )

        return hashlib.sha256(
            "\n".join(parts).encode("utf-8")
        ).hexdigest()