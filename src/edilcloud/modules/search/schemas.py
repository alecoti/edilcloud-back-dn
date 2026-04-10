from ninja import Schema


class SearchActionSchema(Schema):
    id: str
    href: str
    label: str
    external: bool = False


class SearchItemSchema(Schema):
    id: str
    kind: str
    title: str
    subtitle: str
    snippet: str | None = None
    href: str
    external: bool = False
    actions: list[SearchActionSchema]


class SearchSectionsSchema(Schema):
    projects: list[SearchItemSchema] = []
    tasks: list[SearchItemSchema] = []
    activities: list[SearchItemSchema] = []
    updates: list[SearchItemSchema] = []
    documents: list[SearchItemSchema] = []
    drawings: list[SearchItemSchema] = []
    people: list[SearchItemSchema] = []


class GlobalSearchResponseSchema(Schema):
    query: str
    sections: SearchSectionsSchema
    total: int
