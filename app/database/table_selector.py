import re
from collections import deque
from typing import Any

from app.database.schema import TableInfo
from app.database.schema_intelligence import DatabaseSchemaIntelligence


STOP_WORDS = {
    "a",
    "all",
    "an",
    "and",
    "are",
    "be",
    "by",
    "can",
    "do",
    "does",
    "each",
    "for",
    "from",
    "get",
    "give",
    "how",
    "i",
    "in",
    "is",
    "list",
    "me",
    "of",
    "on",
    "or",
    "show",
    "the",
    "there",
    "to",
    "what",
    "which",
    "who",
    "with",
}


TableKey = tuple[str, str]


def normalize_text(text: str) -> str:
    text = str(text).lower()
    text = text.replace("_", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> set[str]:
    normalized = normalize_text(text)
    words = normalized.split()

    return {
        word
        for word in words
        if word not in STOP_WORDS and len(word) > 1
    }


def singularize(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"

    if word.endswith("ses") and len(word) > 3:
        return word[:-2]

    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]

    return word


def expand_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)

    for token in tokens:
        expanded.add(singularize(token))

    return expanded


def table_key(table: TableInfo) -> TableKey:
    return (
        table.schema_name,
        table.table_name,
    )


def relationship_endpoints(
    relationship: Any,
) -> tuple[TableKey, TableKey]:
    """
    Return the two tables connected by a relationship.

    The selector accepts both declared foreign-key metadata and the
    normalized relationship objects produced by the relationship
    intelligence layer. This keeps table selection independent of
    whether a relationship was declared in SQL Server or inferred and
    data-validated.
    """

    if all(
        hasattr(relationship, attribute)
        for attribute in (
            "left_schema",
            "left_table",
            "right_schema",
            "right_table",
        )
    ):
        return (
            relationship.left_schema,
            relationship.left_table,
        ), (
            relationship.right_schema,
            relationship.right_table,
        )

    if all(
        hasattr(relationship, attribute)
        for attribute in (
            "schema_name",
            "table_name",
            "referenced_schema_name",
            "referenced_table_name",
        )
    ):
        return (
            relationship.schema_name,
            relationship.table_name,
        ), (
            relationship.referenced_schema_name,
            relationship.referenced_table_name,
        )

    raise ValueError(
        "Unsupported relationship metadata: expected either "
        "left/right table fields or foreign-key endpoint fields."
    )


def build_relationship_graph(
    relationships: list[Any],
) -> dict[TableKey, set[TableKey]]:
    """
    Build a generic undirected table relationship graph.

    Relationships may be declared foreign keys or normalized
    relationships discovered and validated from database data.
    No business-specific table or column knowledge is encoded.
    """

    graph: dict[TableKey, set[TableKey]] = {}

    for relationship in relationships:
        left, right = relationship_endpoints(
            relationship
        )

        graph.setdefault(left, set())
        graph.setdefault(right, set())

        graph[left].add(right)
        graph[right].add(left)

    return graph


def find_shortest_table_path(
    start: TableKey,
    target: TableKey,
    graph: dict[TableKey, set[TableKey]],
) -> list[TableKey] | None:
    """
    Find the shortest relationship path between two tables.

    Breadth-first search is used so the returned path contains
    the minimum number of relationship hops.
    """

    if start == target:
        return [start]

    if start not in graph or target not in graph:
        return None

    queue: deque[TableKey] = deque([start])
    previous: dict[TableKey, TableKey | None] = {
        start: None
    }

    while queue:
        current = queue.popleft()

        for neighbor in graph.get(current, set()):
            if neighbor in previous:
                continue

            previous[neighbor] = current

            if neighbor == target:
                path: list[TableKey] = []
                node: TableKey | None = target

                while node is not None:
                    path.append(node)
                    node = previous[node]

                path.reverse()
                return path

            queue.append(neighbor)

    return None


def expand_selected_tables_by_relationships(
    selected_tables: list[dict[str, Any]],
    relationships: Any,
) -> list[dict[str, Any]]:
    """
    Add intermediate tables required to connect selected tables.

    Example of the generic behavior:

        Table A
           |
        Table B
           |
        Table C

    If the question selects A and C but B was not selected
    by lexical matching, B is automatically added.

    Consumes either the canonical RelationshipGraph from Phase 5
    or a collection of declared/inferred relationships.
    """

    if len(selected_tables) < 2 or not relationships:
        return selected_tables

    is_graph_object = hasattr(relationships, "find_shortest_path")

    if not is_graph_object:
        graph = build_relationship_graph(
            relationships
        )

    selected_keys: list[TableKey] = [
        (
            item["schema"],
            item["table"],
        )
        for item in selected_tables
    ]

    selected_key_set = set(selected_keys)

    # ---------------------------------------------------------
    # Connect every selected table to the others through the
    # shortest available relationship path.
    # ---------------------------------------------------------

    relationship_tables: set[TableKey] = set()

    for index, start in enumerate(selected_keys):
        for target in selected_keys[index + 1:]:
            if is_graph_object:
                path = relationships.find_shortest_path(start, target)
            else:
                path = find_shortest_table_path(
                    start,
                    target,
                    graph,
                )

            if path is None:
                continue

            relationship_tables.update(path)

    # ---------------------------------------------------------
    # Add only tables that were not already selected.
    # ---------------------------------------------------------

    expanded = list(selected_tables)

    existing_keys = set(selected_key_set)

    for item in selected_tables:
        item_key = (
            item["schema"],
            item["table"],
        )

        if item_key not in relationship_tables:
            continue

    for relationship_table in relationship_tables:
        if relationship_table in existing_keys:
            continue

        expanded.append(
            {
                "schema": relationship_table[0],
                "table": relationship_table[1],
                "score": 0,
                "relationship_required": True,
            }
        )

        existing_keys.add(relationship_table)

    return expanded


def score_table(
    question: str,
    table: TableInfo,
    intelligence: DatabaseSchemaIntelligence | None = None,
) -> int:
    """
    Score a database table using only structural metadata.

    Matching priority:

    1. Specific table-name matches
    2. Column-name matches
    3. Schema-name matches

    No business/domain-specific table names, column names,
    entities, or semantic mappings are used.
    """

    if intelligence is not None:
        return intelligence.score_table(question, table)

    question_tokens = expand_tokens(
        tokenize(question)
    )

    table_name_tokens = expand_tokens(
        tokenize(table.table_name)
    )

    schema_name_tokens = expand_tokens(
        tokenize(table.schema_name)
    )

    score = 0

    # ---------------------------------------------------------
    # Table-name matching
    # ---------------------------------------------------------

    table_matches = (
        question_tokens & table_name_tokens
    )

    score += len(table_matches) * 10

    # ---------------------------------------------------------
    # Question coverage
    # ---------------------------------------------------------

    if question_tokens:
        matched_ratio = (
            len(table_matches)
            / len(question_tokens)
        )

        score += int(matched_ratio * 10)

    # ---------------------------------------------------------
    # Column-name matching
    # ---------------------------------------------------------

    MAX_COLUMN_EVIDENCE = 12
    column_score = 0

    for column in table.columns:
        column_tokens = expand_tokens(
            tokenize(column.name)
        )

        column_matches = (
            question_tokens & column_tokens
        )

        column_score += len(column_matches) * 2

    score += min(column_score, MAX_COLUMN_EVIDENCE)

    # ---------------------------------------------------------
    # Schema-name matching
    # ---------------------------------------------------------

    schema_matches = (
        question_tokens & schema_name_tokens
    )

    score += len(schema_matches)

    return score


def extract_entity_target(question: str) -> str:
    """
    Extract the target entity/table phrase from a natural-language question.

    Handles metadata/structural inquiries such as:
      'List column names of event topics' -> 'event topics'
      'Show column names of event staff' -> 'event staff'
      'What are the columns of customer orders' -> 'customer orders'
      'List columns of order items' -> 'order items'
      'Show columns of product categories' -> 'product categories'
      'How many rows are in event topics' -> 'event topics'
      'Row count of site details' -> 'site details'

    If no structural pattern is matched, returns the original question.
    """
    text = (question or "").strip()
    if not text:
        return text

    patterns = [
        # "list column names of X", "show columns in X", "what are the fields of X"
        r"^(?:list|show|what\s+are|display|get|give|print|tell\s+me\s+the|find)?\s*(?:all\s+)?(?:the\s+)?(?:column|field)s?\s*(?:name|names)?\s*(?:of|for|in|from)\s+(.+)$",
        # "how many columns does X have", "columns in X"
        r"^(?:how\s+many\s+)?(?:column|field)s?\s+(?:does|in|for|of)\s+(.+?)(?:\s+have)?(?:\s*\?)?$",
        # "how many rows in X", "how many records are in X"
        r"^(?:how\s+many\s+)?(?:row|record|entry|entries)s?\s+(?:are\s+)?(?:in|for|of)\s+(.+?)(?:\s*\?)?$",
        # "row count of X", "record count in X"
        r"^(?:row|record)\s+count\s+(?:of|for|in)\s+(.+?)(?:\s*\?)?$",
        # "number of rows in X", "number of records of X"
        r"^(?:number\s+of\s+)?(?:rows|records)\s+(?:in|of|for)\s+(.+?)(?:\s*\?)?$",
        # "describe X", "schema of X", "structure of X"
        r"^(?:describe|schema\s+of|structure\s+of)\s+(.+?)(?:\s*\?)?$",
        # "X column names", "X columns"
        r"^(.+?)\s+(?:column|field)s?\s*(?:name|names)?(?:\s*\?)?$",
    ]

    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            extracted = match.group(1).strip().rstrip("?.")
            if extracted:
                return extracted

    return text


def select_tables(
    question: str,
    schema: list[TableInfo],
    max_tables: int = 5,
    relationships: list[Any] | None = None,
    intelligence: DatabaseSchemaIntelligence | None = None,
    entity_resolver: Any | None = None,
    relationship_service: Any | None = None,
    vector_service: Any | None = None,
    schema_fingerprint: str | None = None,
) -> list[dict[str, Any]]:
    """
    Select relevant database tables and automatically include
    intermediate relationship tables when required.

    Initial selection combines:
    - EntityResolver (compound entity+attribute matching, explainable evidence,
      and capped column scoring)
    - Lexical metadata scoring (schema name, table name, column names)
    - Semantic vector similarity via pgvector (when vector_service is available)

    Relationship expansion uses:
    - declared foreign keys
    - inferred relationships that have been validated by the
      relationship intelligence layer

    No business-specific knowledge is encoded.
    """

    target_phrase = extract_entity_target(question)

    # If entity_resolver was not explicitly supplied, attempt to create
    # one so table selection always benefits from compound phrase matching.
    if entity_resolver is None and schema:
        try:
            from app.database.entity_resolver import EntityResolver
            from app.database.schema import DatabaseSchema
            entity_resolver = EntityResolver(DatabaseSchema(tables=schema))
        except Exception:
            entity_resolver = None

    entity_scores: dict[tuple[str, str], float] = {}
    if entity_resolver is not None:
        try:
            resolution = entity_resolver.resolve(target_phrase, limit=len(schema))
            for candidate in resolution.candidates:
                entity_scores[(candidate.schema_name, candidate.table_name)] = candidate.score

            if target_phrase != question:
                q_resolution = entity_resolver.resolve(question, limit=len(schema))
                for candidate in q_resolution.candidates:
                    key = (candidate.schema_name, candidate.table_name)
                    entity_scores[key] = max(entity_scores.get(key, 0.0), candidate.score * 0.8)
        except Exception:
            entity_scores = {}

    vector_scores: dict[tuple[str, str], float] = {}
    if vector_service is not None and schema_fingerprint:
        try:
            v_query = target_phrase if target_phrase != question else question
            v_candidates = vector_service.search_tables(
                query=v_query,
                schema_fingerprint=schema_fingerprint,
                limit=max_tables * 2,
                min_similarity=0.06,
            )
            for vc in v_candidates:
                v_key = (vc.schema_name, vc.table_name)
                vector_scores[v_key] = min(25.0, vc.similarity * 100.0)

            if target_phrase != question:
                v_q_candidates = vector_service.search_tables(
                    query=question,
                    schema_fingerprint=schema_fingerprint,
                    limit=max_tables * 2,
                    min_similarity=0.06,
                )
                for vc in v_q_candidates:
                    v_key = (vc.schema_name, vc.table_name)
                    q_score = min(25.0, vc.similarity * 100.0) * 0.8
                    vector_scores[v_key] = max(vector_scores.get(v_key, 0.0), q_score)
        except Exception:
            vector_scores = {}

    scored_tables: list[dict[str, Any]] = []

    for table in schema:
        key = (table.schema_name, table.table_name)
        er_score = entity_scores.get(key, 0.0)
        v_score = vector_scores.get(key, 0.0)
        lexical_score = score_table(
            target_phrase if target_phrase != question else question,
            table,
            intelligence=intelligence,
        )

        base_score = max(er_score, lexical_score)
        if base_score > 0 and v_score > 0:
            # Both deterministic and vector signals agree: boost confidence
            score = int(base_score + min(10.0, v_score * 0.4))
        elif base_score > 0:
            score = int(base_score)
        elif v_score >= 25.0:
            # Semantic vector match without direct lexical match (e.g. synonyms)
            score = int(v_score)
        else:
            score = 0

        if score > 0:
            scored_tables.append(
                {
                    "schema": table.schema_name,
                    "table": table.table_name,
                    "score": score,
                    "relationship_required": False,
                }
            )

    scored_tables.sort(
        key=lambda item: (
            -item["score"],
            item["schema"],
            item["table"],
        )
    )

    # ---------------------------------------------------------
    # Initial lexical / entity selection.
    # ---------------------------------------------------------

    is_column_name_req = bool(
        re.search(r"\b(column|field)s?\b.*\b(name|names|list|listed)\b", question, re.IGNORECASE)
        or re.search(r"\b(name|names|list|listed)\b.*\b(column|field)s?\b", question, re.IGNORECASE)
        or re.search(r"\b(column|field)s?\s+(?:of|for|in|from)\b", question, re.IGNORECASE)
    )

    # For metadata requests where a single target entity was requested
    # and a highly relevant table has been identified, select that
    # specific table instead of needlessly pulling in unrelated tables.
    if is_column_name_req and target_phrase != question and scored_tables:
        if scored_tables[0]["score"] >= 25:
            selected_tables = scored_tables[:1]
        else:
            selected_tables = scored_tables[:max_tables]
    else:
        selected_tables = scored_tables[:max_tables]

    # ---------------------------------------------------------
    # Relationship-aware expansion (Phase 5 canonical flow).
    #
    # Intermediate / bridge tables are added using the canonical
    # relationship knowledge (declared foreign keys and validated
    # inferred relationships).
    # ---------------------------------------------------------

    if relationship_service is not None and len(selected_tables) >= 2:
        selected_keys = [(item["schema"], item["table"]) for item in selected_tables]
        if not relationship_service.is_connected(selected_keys):
            relationship_service.discover(selected_keys, include_bridges=True)
        selected_tables = expand_selected_tables_by_relationships(
            selected_tables,
            relationship_service.get_graph(),
        )
    elif relationships:
        selected_tables = (
            expand_selected_tables_by_relationships(
                selected_tables,
                relationships,
            )
        )

    return selected_tables