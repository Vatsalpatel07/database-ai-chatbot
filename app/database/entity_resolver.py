"""
Generic entity/schema resolution.

Official Phase 6:
Generic Entity / Schema Resolution.

This module:
- performs deterministic entity-to-table matching
- does not call an LLM
- does not execute SQL
- uses DatabaseSchemaIntelligence
- produces explainable evidence
- supports generic compound phrases such as:
    "event name"
    "site status"
    "customer email"
    "order date"
"""

from dataclasses import dataclass

from app.database.schema import DatabaseSchema
from app.database.schema_intelligence import (
    DatabaseSchemaIntelligence,
)


@dataclass(frozen=True)
class EntityCandidate:
    """A possible table representing the requested entity."""

    schema_name: str
    table_name: str
    score: float
    evidence: list[str]


@dataclass(frozen=True)
class EntityResolutionResult:
    """Result of resolving a natural-language entity phrase."""

    phrase: str
    candidates: list[EntityCandidate]
    confident: bool


class EntityResolver:
    """
    Resolve a natural-language entity phrase to likely database tables.

    Resolution is deterministic and based only on database metadata.
    """

    EXACT_TABLE_MATCH_SCORE = 30.0
    CORE_TABLE_MATCH_SCORE = 25.0
    TABLE_TOKEN_SCORE = 12.0
    ENTITY_TOKEN_SCORE = 7.0

    COLUMN_TOKEN_SCORE = 2.0
    IDENTIFIER_EVIDENCE_SCORE = 1.0
    NAME_EVIDENCE_SCORE = 1.0

    MAX_COLUMN_EVIDENCE_SCORE = 12.0

    COMPOUND_ENTITY_MATCH_SCORE = 8.0
    COMPOUND_ATTRIBUTE_MATCH_SCORE = 8.0
    COMPOUND_EXACT_ATTRIBUTE_SCORE = 4.0

    # Additional score when a column represents the complete
    # entity + attribute combination.
    #
    # Examples:
    #   site + name     -> site_name
    #   customer + name -> customer_name
    #   order + date    -> order_date
    COMPOUND_EXACT_ENTITY_ATTRIBUTE_COLUMN_SCORE = 10.0

    COMPOUND_MAX_ATTRIBUTE_SCORE = 18.0

    CONFIDENT_MIN_SCORE = 20.0
    CONFIDENCE_RATIO = 1.5

    def __init__(
        self,
        schema: DatabaseSchema,
    ) -> None:
        self.schema = schema
        self.intelligence = DatabaseSchemaIntelligence(
            schema
        )

    def resolve(
        self,
        phrase: str,
        limit: int = 5,
    ) -> EntityResolutionResult:
        """
        Resolve an entity phrase to ranked table candidates.

        Supports simple phrases:

            "events"
            "sites"
            "customers"

        and compound phrases:

            "event name"
            "site status"
            "customer email"
            "order date"
        """

        phrase = (phrase or "").strip()

        if not phrase:
            return EntityResolutionResult(
                phrase=phrase,
                candidates=[],
                confident=False,
            )

        query_tokens = self.intelligence.tokenize(
            phrase
        )

        if not query_tokens:
            return EntityResolutionResult(
                phrase=phrase,
                candidates=[],
                confident=False,
            )

        normalized_phrase = (
            self.intelligence.normalize_identifier(
                phrase
            )
        )

        compound_tokens = self._split_compound_phrase(
            phrase
        )

        compound_entity_tokens, compound_attribute_tokens = (
            compound_tokens
        )

        candidates: list[EntityCandidate] = []

        for table in self.schema.tables:
            profile = self.intelligence.get_table_profile(
                table.schema_name,
                table.table_name,
            )

            if profile is None:
                continue

            score = 0.0
            evidence: list[str] = []

            table_tokens = set(
                profile.table_tokens
            )

            entity_tokens = set(
                profile.entity_tokens
            )

            normalized_table = (
                self.intelligence.normalize_identifier(
                    table.table_name
                )
            )

            # ---------------------------------------------------------
            # 1. Exact and core table-name match
            # ---------------------------------------------------------

            is_exact_match = (normalized_phrase == normalized_table)

            phrase_words = normalized_phrase.split()
            table_words = normalized_table.split()

            def _sing(w: str) -> str:
                if w.endswith("ies") and len(w) > 3:
                    return w[:-3] + "y"
                if w.endswith("ses") and len(w) > 3:
                    return w[:-2]
                if w.endswith("s") and not w.endswith("ss"):
                    return w[:-1]
                return w

            p_sing = " ".join(_sing(w) for w in phrase_words)
            t_sing = " ".join(_sing(w) for w in table_words)
            core_sing = " ".join(_sing(w) for w in table_words[1:]) if len(table_words) > 1 else t_sing

            is_core_match = (
                len(phrase_words) >= 2
                and (p_sing == core_sing or p_sing in t_sing)
            ) or (
                len(phrase_words) >= 1
                and p_sing == core_sing
            )

            if is_exact_match:
                score += self.EXACT_TABLE_MATCH_SCORE
                evidence.append(
                    "exact table name match"
                )
            elif is_core_match:
                score += self.CORE_TABLE_MATCH_SCORE
                evidence.append(
                    f"core table name match: {normalized_phrase}"
                )

            # ---------------------------------------------------------
            # 2. Table-name token match
            # ---------------------------------------------------------

            table_overlap = (
                query_tokens & table_tokens
            )

            if table_overlap:
                score += (
                    self.TABLE_TOKEN_SCORE
                    * len(table_overlap)
                )

                evidence.append(
                    "table name token match: "
                    + ", ".join(
                        sorted(table_overlap)
                    )
                )

            # ---------------------------------------------------------
            # 3. Entity-token match
            #
            # For a compound phrase, attribute tokens are explicitly
            # excluded from ordinary entity evidence.
            #
            # Example:
            #
            #   event name
            #
            # "name" must not become an entity merely because it appears
            # in many name-bearing columns.
            # ---------------------------------------------------------

            entity_overlap = (
                query_tokens & entity_tokens
            )

            if compound_entity_tokens:
                entity_overlap = (
                    entity_overlap
                    & compound_entity_tokens
                )

            entity_only = (
                entity_overlap - table_overlap
            )

            if entity_only:
                score += (
                    self.ENTITY_TOKEN_SCORE
                    * len(entity_only)
                )

                evidence.append(
                    "entity token match: "
                    + ", ".join(
                        sorted(entity_only)
                    )
                )

            # ---------------------------------------------------------
            # 4. Standard column evidence
            # ---------------------------------------------------------

            column_score, column_evidence = (
                self._calculate_column_evidence(
                    query_tokens=query_tokens,
                    profile=profile,
                )
            )

            score += column_score
            evidence.extend(column_evidence)

            # ---------------------------------------------------------
            # 5. Compound phrase evidence
            # ---------------------------------------------------------

            compound_score, compound_evidence = (
                self._calculate_compound_evidence(
                    entity_tokens=compound_entity_tokens,
                    attribute_tokens=compound_attribute_tokens,
                    profile=profile,
                    table_overlap=table_overlap,
                )
            )

            score += compound_score
            evidence.extend(compound_evidence)

            if score <= 0:
                continue

            candidates.append(
                EntityCandidate(
                    schema_name=table.schema_name,
                    table_name=table.table_name,
                    score=score,
                    evidence=list(
                        dict.fromkeys(evidence)
                    ),
                )
            )

        candidates.sort(
            key=lambda candidate: (
                -candidate.score,
                candidate.schema_name.casefold(),
                candidate.table_name.casefold(),
            )
        )

        if limit <= 0:
            candidates = []
        else:
            candidates = candidates[:limit]

        return EntityResolutionResult(
            phrase=phrase,
            candidates=candidates,
            confident=self._is_confident(
                candidates
            ),
        )

    def _calculate_column_evidence(
        self,
        query_tokens: set[str],
        profile,
    ) -> tuple[float, list[str]]:
        """
        Calculate ordinary supporting column evidence.

        Column evidence is deliberately capped so that a table with many
        repeated matching columns cannot overwhelm stronger table/entity
        evidence.
        """

        column_score = 0.0
        evidence: list[str] = []

        matched_columns: list[
            tuple[float, str]
        ] = []

        for column in profile.columns:
            column_overlap = (
                query_tokens
                & set(column.tokens)
            )

            if not column_overlap:
                continue

            current_score = (
                self.COLUMN_TOKEN_SCORE
                * len(column_overlap)
            )

            if "identifier" in column.roles:
                current_score += (
                    self.IDENTIFIER_EVIDENCE_SCORE
                )

            if "name" in column.roles:
                current_score += (
                    self.NAME_EVIDENCE_SCORE
                )

            matched_columns.append(
                (
                    current_score,
                    column.name,
                )
            )

        matched_columns.sort(
            key=lambda item: (
                -item[0],
                item[1].casefold(),
            )
        )

        for current_score, column_name in matched_columns:
            remaining = (
                self.MAX_COLUMN_EVIDENCE_SCORE
                - column_score
            )

            if remaining <= 0:
                break

            applied_score = min(
                current_score,
                remaining,
            )

            column_score += applied_score

            column = next(
                (
                    item
                    for item in profile.columns
                    if item.name == column_name
                ),
                None,
            )

            if column is None:
                continue

            if column.roles:
                evidence.append(
                    f"column match: {column.name} "
                    f"({', '.join(sorted(column.roles))})"
                )
            else:
                evidence.append(
                    f"column match: {column.name}"
                )

            if "identifier" in column.roles:
                evidence.append(
                    "identifier column evidence: "
                    f"{column.name}"
                )

            if "name" in column.roles:
                evidence.append(
                    "name column evidence: "
                    f"{column.name}"
                )

        return column_score, evidence

    def _calculate_compound_evidence(
        self,
        entity_tokens: set[str],
        attribute_tokens: set[str],
        profile,
        table_overlap: set[str],
    ) -> tuple[float, list[str]]:
        """
        Calculate evidence for an entity + attribute phrase.

        Example:

            "site name"

        is interpreted as:

            entity:
                site

            attribute:
                name

        A strong compound column match occurs when the column contains
        both sides of the phrase:

            site + name -> site_name
        """

        if not entity_tokens:
            return 0.0, []

        if not attribute_tokens:
            return 0.0, []

        entity_matches = (
            entity_tokens
            & table_overlap
        )

        if not entity_matches:
            return 0.0, []

        attribute_matches: list[
            tuple[
                float,
                str,
                set[str],
                bool,
            ]
        ] = []

        expected_compound_tokens = (
            entity_matches
            | attribute_tokens
        )

        for column in profile.columns:
            column_tokens = set(
                column.tokens
            )

            attribute_overlap = (
                attribute_tokens
                & column_tokens
            )

            if not attribute_overlap:
                continue

            current_score = (
                self.COMPOUND_ATTRIBUTE_MATCH_SCORE
                * len(attribute_overlap)
            )

            normalized_column = (
                self.intelligence.normalize_identifier(
                    column.name
                )
            )

            normalized_attribute = (
                self.intelligence.normalize_identifier(
                    " ".join(
                        sorted(attribute_tokens)
                    )
                )
            )

            exact_attribute = (
                normalized_column
                == normalized_attribute
            )

            if exact_attribute:
                current_score += (
                    self.COMPOUND_EXACT_ATTRIBUTE_SCORE
                )

            # Stronger evidence when the actual column contains both
            # entity and attribute tokens.
            complete_compound_match = (
                expected_compound_tokens
                <= column_tokens
            )

            if complete_compound_match:
                current_score += (
                    self.COMPOUND_EXACT_ENTITY_ATTRIBUTE_COLUMN_SCORE
                )

            attribute_matches.append(
                (
                    current_score,
                    column.name,
                    attribute_overlap,
                    complete_compound_match,
                )
            )

        if not attribute_matches:
            return 0.0, []

        attribute_matches.sort(
            key=lambda item: (
                -item[0],
                item[1].casefold(),
            )
        )

        score = 0.0
        evidence: list[str] = []

        score += min(
            self.COMPOUND_ENTITY_MATCH_SCORE
            * len(entity_matches),
            self.COMPOUND_ENTITY_MATCH_SCORE * 2,
        )

        evidence.append(
            "compound entity match: "
            + ", ".join(
                sorted(entity_matches)
            )
        )

        remaining = (
            self.COMPOUND_MAX_ATTRIBUTE_SCORE
        )

        for (
            current_score,
            column_name,
            overlap,
            complete_compound_match,
        ) in attribute_matches:
            if remaining <= 0:
                break

            applied_score = min(
                current_score,
                remaining,
            )

            score += applied_score
            remaining -= applied_score

            if complete_compound_match:
                evidence.append(
                    "compound attribute match: "
                    f"{column_name}"
                )
                evidence.append(
                    "compound entity+attribute "
                    "column match: "
                    f"{column_name}"
                )
            else:
                evidence.append(
                    "compound attribute match: "
                    f"{column_name} "
                    f"({', '.join(sorted(overlap))})"
                )

        return score, evidence

    def _split_compound_phrase(
        self,
        phrase: str,
    ) -> tuple[set[str], set[str]]:
        """
        Split a phrase into entity and attribute token groups.

        Entity vocabulary comes only from table-name vocabulary.

        Attribute vocabulary comes from column vocabulary.

        Therefore generic words such as:

            name
            status
            date

        cannot become entity tokens merely because they occur in columns.
        """

        tokens = set(
            self.intelligence.tokenize(
                phrase
            )
        )

        if len(tokens) < 2:
            return set(), set()

        table_vocabulary: set[str] = set()
        column_vocabulary: set[str] = set()

        for profile in self.intelligence.profiles():
            table_vocabulary.update(
                profile.table_tokens
            )

            for column in profile.columns:
                column_vocabulary.update(
                    column.tokens
                )

        entity_tokens = (
            tokens
            & table_vocabulary
        )

        if not entity_tokens:
            return set(), set()

        SCHEMA_COMMAND_WORDS = {
            "column",
            "columns",
            "field",
            "fields",
            "table",
            "tables",
            "record",
            "records",
            "row",
            "rows",
        }

        attribute_tokens = (
            tokens
            - entity_tokens
            - SCHEMA_COMMAND_WORDS
        ) & column_vocabulary

        if not attribute_tokens:
            return set(), set()

        return (
            entity_tokens,
            attribute_tokens,
        )

    @classmethod
    def _is_confident(
        cls,
        candidates: list[EntityCandidate],
    ) -> bool:
        """
        Decide whether the top candidate is sufficiently distinct.

        Confidence is intentionally conservative. If multiple tables have
        nearly identical semantic evidence, the resolver reports that the
        result is ambiguous instead of choosing one arbitrarily.
        """

        if not candidates:
            return False

        top = candidates[0]

        if top.score < cls.CONFIDENT_MIN_SCORE:
            return False

        if len(candidates) == 1:
            return True

        second = candidates[1]

        if second.score <= 0:
            return True

        return (
            top.score
            >= second.score
            * cls.CONFIDENCE_RATIO
        )