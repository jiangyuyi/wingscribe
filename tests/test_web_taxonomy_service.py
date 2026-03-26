from src.web import taxonomy_service


def test_search_species_closes_manager():
    class StubManager:
        def __init__(self):
            self.closed = False

        def search_species(self, query, limit):
            return [(query, limit)]

        def close(self):
            self.closed = True

    manager = StubManager()
    result = taxonomy_service.search_species(lambda: manager, "tit")

    assert result == [("tit", 20)]
    assert manager.closed is True


def test_get_taxonomy_tree_uses_fast_path_without_date():
    class StubManager:
        def __init__(self):
            self.closed = False
            self.calls = []

        def get_taxonomy_tree_fast(self, include_empty):
            self.calls.append(("fast", include_empty))
            return ["fast"]

        def get_taxonomy_tree(self, include_empty, date_filter):
            self.calls.append(("date", include_empty, date_filter))
            return ["date"]

        def close(self):
            self.closed = True

    manager = StubManager()
    result = taxonomy_service.get_taxonomy_tree(lambda: manager, include_empty=False)

    assert result == ["fast"]
    assert manager.calls == [("fast", False)]
    assert manager.closed is True


def test_search_taxonomy_closes_manager():
    class StubManager:
        def __init__(self):
            self.closed = False

        def search_taxonomy(self, query, limit):
            return [{"query": query, "limit": limit}]

        def close(self):
            self.closed = True

    manager = StubManager()
    result = taxonomy_service.search_taxonomy(lambda: manager, "sparrow", 5)

    assert result == [{"query": "sparrow", "limit": 5}]
    assert manager.closed is True


def test_get_photos_by_taxonomy_prefers_cn_filters_and_closes_resources():
    class StubManager:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class StubCursor:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params):
            self.executed.append((sql, params))

        def fetchone(self):
            return [1]

        def fetchall(self):
            return [{"original_path": "raw.jpg", "file_path": "processed.jpg"}]

    class StubConn:
        def __init__(self):
            self.cursor_obj = StubCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_obj

        def close(self):
            self.closed = True

    manager = StubManager()
    conn = StubConn()

    result = taxonomy_service.get_photos_by_taxonomy(
        lambda: manager,
        lambda: conn,
        lambda path: f"/raw/{path}",
        lambda path: f"/processed/{path}",
        order_cn="雀形目",
        order_sci="Passeriformes",
        family_cn="山雀科",
        family_sci="Paridae",
        limit=10,
        offset=5,
    )

    assert result["total_count"] == 1
    assert result["photos"][0]["web_raw_path"] == "/raw/raw.jpg"
    assert result["photos"][0]["web_processed_path"] == "/processed/processed.jpg"
    assert conn.cursor_obj.executed[0][1] == ["雀形目", "山雀科"]
    assert conn.cursor_obj.executed[1][1] == ["雀形目", "山雀科", 10, 5]
    assert manager.closed is True
    assert conn.closed is True
