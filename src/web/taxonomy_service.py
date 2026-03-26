import json
from typing import Optional


def search_species(create_db_manager, q: str):
    manager = create_db_manager()
    try:
        return manager.search_species(q, limit=20)
    finally:
        manager.close()


def get_taxonomy_tree(create_db_manager, include_empty: bool = True, date: str = None):
    manager = create_db_manager()
    try:
        if date:
            return manager.get_taxonomy_tree(include_empty=include_empty, date_filter=date)
        return manager.get_taxonomy_tree_fast(include_empty=include_empty)
    finally:
        manager.close()


def get_taxonomy_stats(create_db_manager, level: str, date: str = None):
    manager = create_db_manager()
    try:
        return manager.get_stats_by_level(level=level, date_filter=date)
    finally:
        manager.close()


def get_photos_by_taxonomy(
    create_db_manager,
    get_db_conn,
    resolve_web_path,
    resolve_processed_web_path,
    order_cn: Optional[str] = None,
    order_sci: Optional[str] = None,
    family_cn: Optional[str] = None,
    family_sci: Optional[str] = None,
    genus_cn: Optional[str] = None,
    genus_sci: Optional[str] = None,
    scientific_name: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    manager = create_db_manager()
    conn = get_db_conn()
    cursor = conn.cursor()

    try:
        query_parts = ["1=1"]
        params = []

        if order_cn:
            query_parts.append("t.order_cn = ?")
            params.append(order_cn)
        elif order_sci:
            query_parts.append("t.order_sci = ?")
            params.append(order_sci)

        if family_cn:
            query_parts.append("t.family_cn = ?")
            params.append(family_cn)
        elif family_sci:
            query_parts.append("t.family_sci = ?")
            params.append(family_sci)

        if genus_cn:
            query_parts.append("t.genus_cn = ?")
            params.append(genus_cn)
        elif genus_sci:
            query_parts.append("t.genus_sci = ?")
            params.append(genus_sci)

        if scientific_name:
            query_parts.append("t.scientific_name = ?")
            params.append(scientific_name)
        if date:
            query_parts.append("p.captured_date = ?")
            params.append(date)

        where_clause = "WHERE " + " AND ".join(query_parts)

        count_sql = f"""
            SELECT COUNT(DISTINCT p.id)
            FROM taxonomy t
            JOIN photos p ON LOWER(t.scientific_name) = LOWER(p.scientific_name)
            {where_clause}
        """
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]

        sql = f"""
            SELECT p.*
            FROM taxonomy t
            JOIN photos p ON LOWER(t.scientific_name) = LOWER(p.scientific_name)
            {where_clause}
            ORDER BY p.captured_date DESC, p.id DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(sql, params + [limit, offset])
        photos = cursor.fetchall()

        display_photos = []
        for photo in photos:
            photo_dict = dict(photo)
            photo_dict["web_raw_path"] = resolve_web_path(photo_dict.get("original_path"))
            photo_dict["web_processed_path"] = resolve_processed_web_path(photo_dict.get("file_path"))
            display_photos.append(photo_dict)

        return {
            "photos": display_photos,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }
    finally:
        manager.close()
        conn.close()


def search_taxonomy(create_db_manager, q: str, limit: int = 20):
    manager = create_db_manager()
    try:
        return manager.search_taxonomy(query=q, limit=limit)
    finally:
        manager.close()


def build_user_comment_from_candidates(candidates_json: Optional[str]):
    if not candidates_json:
        return []
    return json.loads(candidates_json)
