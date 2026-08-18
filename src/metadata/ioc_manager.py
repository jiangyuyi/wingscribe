import sqlite3
import logging
import pandas as pd
import zipfile
import xml.etree.ElementTree as ET
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Optional

class IOCManager:
    def __init__(
        self,
        db_path: str,
        base_dir: str = "",
        source_base_dir: str = "",
        processed_base_dir: str = ""
    ):
        self.db_path = db_path
        self._use_shared_connection_only = db_path == ":memory:"
        self._write_lock = threading.Lock()
        if base_dir and not source_base_dir:
            source_base_dir = base_dir
        self.source_base_dir = Path(source_base_dir) if source_base_dir else None
        self.processed_base_dir = Path(processed_base_dir) if processed_base_dir else None
        # Ensure parent directory exists
        db_file = Path(db_path)
        self._db_file = db_file
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = self._create_connection()
        # Removed persistent self.cursor for thread safety
        self._init_db()

    def _create_connection(self):
        conn = sqlite3.connect(str(self._db_file), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _operation_connection(self, write: bool = False):
        if self._use_shared_connection_only:
            yield self.conn
            return

        if write:
            with self._write_lock:
                conn = self._create_connection()
                try:
                    yield conn
                    conn.commit()
                finally:
                    conn.close()
            return

        conn = self._create_connection()
        try:
            yield conn
        finally:
            conn.close()

    def _abs_to_rel(self, abs_path: str, base_dir: Optional[Path]) -> str:
        """Convert absolute path to relative path based on base_dir."""
        if not base_dir or not abs_path:
            return abs_path
        try:
            return Path(abs_path).relative_to(base_dir).as_posix()
        except ValueError:
            return abs_path  # Not under base_dir, keep as is

    def _rel_to_abs(self, rel_path: str, base_dir: Optional[Path]) -> str:
        """Convert relative path to absolute path based on base_dir."""
        if not base_dir or not rel_path:
            return rel_path
        p = Path(rel_path)
        if p.is_absolute():
            return rel_path
        return str(base_dir / p)

    def to_storage_original_path(self, abs_path: str) -> str:
        return self._abs_to_rel(abs_path, self.source_base_dir)

    def to_storage_processed_path(self, abs_path: str) -> str:
        return self._abs_to_rel(abs_path, self.processed_base_dir)

    def resolve_original_path(self, stored_path: str) -> str:
        return self._rel_to_abs(stored_path, self.source_base_dir)

    def resolve_processed_path(self, stored_path: str) -> str:
        return self._rel_to_abs(stored_path, self.processed_base_dir)

    def _init_db(self):
        # Taxonomy Table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS taxonomy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scientific_name TEXT UNIQUE,
                chinese_name TEXT,
                family_cn TEXT,
                order_cn TEXT,
                genus_cn TEXT,
                genus_sci TEXT,
                family_sci TEXT,
                order_sci TEXT,
                english_name TEXT
            )
        ''')
        # Create index for faster search (basic indexes that should always exist)
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_sci_name ON taxonomy(scientific_name)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_cn_name ON taxonomy(chinese_name)')

        # Photos Table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                filename TEXT,
                original_path TEXT,
                file_hash TEXT,
                captured_date TEXT,
                location_tag TEXT,
                primary_bird_cn TEXT,
                scientific_name TEXT,
                confidence_score REAL,
                label_source TEXT NOT NULL DEFAULT 'automatic',
                manual_verified_at TEXT,
                width INTEGER,
                height INTEGER
            )
        ''')

        # Scan History Table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT,
                end_time TEXT,
                range_start TEXT,
                range_end TEXT,
                processed_count INTEGER,
                duration_seconds REAL,
                status TEXT
            )
        ''')

        # Migration - Photos table
        try:
            self.conn.execute("SELECT file_hash, original_path, candidates_json FROM photos LIMIT 1")
        except sqlite3.OperationalError:
            logging.info("Migrating database: Adding new columns to photos...")
            try: self.conn.execute("ALTER TABLE photos ADD COLUMN file_hash TEXT")
            except: pass
            try: self.conn.execute("ALTER TABLE photos ADD COLUMN original_path TEXT")
            except: pass
            try: self.conn.execute("ALTER TABLE photos ADD COLUMN candidates_json TEXT")
            except: pass

        # Migration - Add web path columns
        try:
            self.conn.execute("SELECT web_processed_path, web_raw_path FROM photos LIMIT 1")
        except sqlite3.OperationalError:
            logging.info("Migrating database: Adding web path columns to photos...")
            try: self.conn.execute("ALTER TABLE photos ADD COLUMN web_processed_path TEXT")
            except: pass
            try: self.conn.execute("ALTER TABLE photos ADD COLUMN web_raw_path TEXT")
            except: pass

        # Human-confirmed labels are the only safe source for future visual prototypes.
        try:
            self.conn.execute("SELECT label_source, manual_verified_at FROM photos LIMIT 1")
        except sqlite3.OperationalError:
            logging.info("Migrating database: Adding photo label provenance columns...")
            try:
                self.conn.execute(
                    "ALTER TABLE photos ADD COLUMN label_source TEXT NOT NULL DEFAULT 'automatic'"
                )
            except sqlite3.OperationalError:
                pass
            try:
                self.conn.execute("ALTER TABLE photos ADD COLUMN manual_verified_at TEXT")
            except sqlite3.OperationalError:
                pass
        self.conn.execute(
            "UPDATE photos SET label_source = 'automatic' "
            "WHERE label_source IS NULL OR label_source = ''"
        )

        # Migration - Taxonomy table (add genus, family_sci, order_sci, english_name)
        try:
            self.conn.execute("SELECT genus_cn, genus_sci, family_sci, order_sci, english_name FROM taxonomy LIMIT 1")
        except sqlite3.OperationalError:
            logging.info("Migrating database: Adding new columns to taxonomy...")
            try: self.conn.execute("ALTER TABLE taxonomy ADD COLUMN genus_cn TEXT")
            except: pass
            try: self.conn.execute("ALTER TABLE taxonomy ADD COLUMN genus_sci TEXT")
            except: pass
            try: self.conn.execute("ALTER TABLE taxonomy ADD COLUMN family_sci TEXT")
            except: pass
            try: self.conn.execute("ALTER TABLE taxonomy ADD COLUMN order_sci TEXT")
            except: pass
            try: self.conn.execute("ALTER TABLE taxonomy ADD COLUMN english_name TEXT")
            except: pass

            # After adding columns, create additional indexes
            try: self.conn.execute("CREATE INDEX IF NOT EXISTS idx_order ON taxonomy(order_cn, order_sci)")
            except: pass
            try: self.conn.execute("CREATE INDEX IF NOT EXISTS idx_family ON taxonomy(family_cn, family_sci)")
            except: pass
            try: self.conn.execute("CREATE INDEX IF NOT EXISTS idx_genus ON taxonomy(genus_cn, genus_sci)")
            except: pass

            self.conn.commit()

        # Create indexes for photos table (for taxonomy tree queries)
        try: self.conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_sci_name ON photos(scientific_name)")
        except: pass
        try: self.conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_date ON photos(captured_date)")
        except: pass
        try:
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_photos_label_source "
                "ON photos(label_source, scientific_name)"
            )
        except sqlite3.OperationalError:
            pass

        # Species Stats Table (for fast taxonomy tree queries)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS species_stats (
                scientific_name TEXT PRIMARY KEY,
                photo_count INTEGER DEFAULT 0,
                order_cn TEXT,
                order_sci TEXT,
                family_cn TEXT,
                family_sci TEXT,
                genus_cn TEXT,
                genus_sci TEXT,
                chinese_name TEXT,
                english_name TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try: self.conn.execute("CREATE INDEX IF NOT EXISTS idx_species_stats_count ON species_stats(photo_count DESC)")
        except: pass
        self.conn.commit()

    def load_genus_mapping(self, cn_excel_path: str) -> Dict[str, str]:
        """
        从动物界-脊索动物门Excel文件加载属中文名映射
        返回 {属拉丁名: 属中文名} 字典
        """
        logging.info(f"Loading genus mapping from {cn_excel_path}...")
        try:
            df = pd.read_excel(cn_excel_path, engine='openpyxl')
            df.columns = [c.strip() for c in df.columns]

            mapping = {}
            for _, row in df.iterrows():
                genus_sci = str(row.get('属拉丁名', '')).strip()
                genus_cn = str(row.get('属中文名', '')).strip()
                if genus_sci and genus_cn and genus_sci != 'nan' and genus_cn != 'nan':
                    mapping[genus_sci] = genus_cn

            logging.info(f"Loaded {len(mapping)} genus mappings")
            return mapping

        except Exception as e:
            logging.error(f"Failed to load genus mapping: {e}")
            return {}

    def load_csv_mapping(self, csv_path: str, sci_col: str, cn_col: str) -> Dict[str, str]:
        """
        从CSV文件加载分类映射
        返回 {拉丁名: 中文名} 字典
        """
        try:
            # Try different encodings
            for encoding in ['utf-8-sig', 'utf-8', 'gbk', 'gb2312']:
                try:
                    df = pd.read_csv(csv_path, encoding=encoding)
                    if sci_col in df.columns and cn_col in df.columns:
                        mapping = {}
                        for _, row in df.iterrows():
                            sci = str(row[sci_col]).strip()
                            cn = str(row[cn_col]).strip()
                            if sci and cn and sci != 'nan' and cn != 'nan':
                                mapping[sci] = cn
                        logging.info(f"Loaded {len(mapping)} mappings from {csv_path}")
                        return mapping
                except:
                    continue
            logging.warning(f"Failed to load mapping from {csv_path}")
            return {}
        except Exception as e:
            logging.error(f"Error loading CSV mapping {csv_path}: {e}")
            return {}

    def _read_excel_as_dataframe(self, excel_path: str) -> pd.DataFrame:
        """
        Read Excel file by parsing XML directly to avoid openpyxl encoding issues.
        This method correctly handles Chinese characters in IOC Excel files.
        """
        import tempfile
        import os

        # Create temp directory for extraction
        temp_dir = tempfile.mkdtemp()

        try:
            # Extract Excel (which is a ZIP file)
            with zipfile.ZipFile(excel_path, 'r') as z:
                z.extractall(temp_dir)

            # Parse shared strings
            shared_strings_path = os.path.join(temp_dir, 'xl', 'sharedStrings.xml')
            if not os.path.exists(shared_strings_path):
                # Fallback to pandas if extraction fails
                return pd.read_excel(excel_path)

            tree = ET.parse(shared_strings_path)
            root = tree.getroot()

            # Use correct namespace prefix
            ns = {'sst': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

            # Build string list
            strings = []
            for item in root.findall('.//sst:si', ns):
                texts = []
                for t in item.findall('.//sst:t', ns):
                    if t.text:
                        texts.append(t.text)
                strings.append(''.join(texts))

            # Parse sheet1
            sheet_path = os.path.join(temp_dir, 'xl', 'worksheets', 'sheet1.xml')
            if not os.path.exists(sheet_path):
                return pd.read_excel(excel_path)

            tree = ET.parse(sheet_path)
            root = tree.getroot()

            rows = root.findall('.//sst:row', ns)
            if not rows:
                return pd.read_excel(excel_path)

            # Parse header row
            header_row = rows[0]
            header_cells = header_row.findall('sst:c', ns)
            header = []
            for cell in header_cells:
                v = cell.find('sst:v', ns)
                if v is not None and v.text:
                    try:
                        idx = int(v.text)
                        header.append(strings[idx] if idx < len(strings) else '')
                    except:
                        header.append('')
                else:
                    is_ = cell.find('sst:is/sst:t', ns)
                    header.append(is_.text if is_ is not None else '')

            # Parse data rows
            data = []
            for row in rows[1:]:  # Skip header
                cells = row.findall('sst:c', ns)
                row_data = {}
                for i, cell in enumerate(cells):
                    if i >= len(header):
                        break
                    v = cell.find('sst:v', ns)
                    if v is not None and v.text:
                        try:
                            idx = int(v.text)
                            row_data[header[i]] = strings[idx] if idx < len(strings) else ''
                        except:
                            row_data[header[i]] = ''
                    else:
                        is_ = cell.find('sst:is/sst:t', ns)
                        row_data[header[i]] = is_.text if is_ is not None else ''
                if row_data:
                    data.append(row_data)

            return pd.DataFrame(data)

        finally:
            # Cleanup temp directory
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def import_from_excel(self, excel_path: str, genus_mapping: Dict[str, str] = None,
                        order_mapping: Dict[str, str] = None, family_mapping: Dict[str, str] = None,
                        refs_dir: str = None):
        """
        Import full IOC list from Excel into taxonomy table.

        Args:
            excel_path: Path to IOC Excel file
            genus_mapping: Optional {属拉丁名: 属中文名} mapping dictionary
            order_mapping: Optional {目拉丁名: 目中文名} mapping dictionary
            family_mapping: Optional {科拉丁名: 科中文名} mapping dictionary
            refs_dir: Optional references directory for loading CSV mappings
        """
        logging.info(f"Importing taxonomy from {excel_path}...")

        # Auto-load CSV mappings if not provided and refs_dir exists
        if refs_dir:
            refs = Path(refs_dir)
            if not genus_mapping:
                genus_csv = refs / 'bird_genus_mapping_complete.csv'
                if genus_csv.exists():
                    genus_mapping = self.load_csv_mapping(str(genus_csv), 'Genus_SCI', 'Genus_CN')
                else:
                    genus_csv = refs / 'bird_genus_mapping.csv'
                    if genus_csv.exists():
                        genus_mapping = self.load_csv_mapping(str(genus_csv), 'Genus_SCI', 'Genus_CN')
            if not order_mapping:
                order_csv = refs / 'bird_order_mapping_complete.csv'
                if order_csv.exists():
                    order_mapping = self.load_csv_mapping(str(order_csv), 'Order_SCI', 'Order_CN')
                else:
                    order_csv = refs / 'bird_order_mapping.csv'
                    if order_csv.exists():
                        order_mapping = self.load_csv_mapping(str(order_csv), 'Order_SCI', 'Order_CN')
            if not family_mapping:
                family_csv = refs / 'bird_family_mapping_complete.csv'
                if family_csv.exists():
                    family_mapping = self.load_csv_mapping(str(family_csv), 'Family_SCI', 'Family_CN')
                else:
                    family_csv = refs / 'bird_family_mapping.csv'
                    if family_csv.exists():
                        family_mapping = self.load_csv_mapping(str(family_csv), 'Family_SCI', 'Family_CN')

        if genus_mapping:
            logging.info(f"Using genus mapping with {len(genus_mapping)} entries")
        if order_mapping:
            logging.info(f"Using order mapping with {len(order_mapping)} entries")
        if family_mapping:
            logging.info(f"Using family mapping with {len(family_mapping)} entries")

        try:
            # Use XML parsing method to correctly read Chinese characters
            df = self._read_excel_as_dataframe(excel_path)
            if df is not None and not df.empty:
                df.columns = [str(c).strip() if hasattr(c, 'strip') else str(c) for c in df.columns]
            else:
                logging.warning("Failed to read Excel file, using pandas fallback")
                df = pd.read_excel(excel_path)
                df.columns = [str(c).strip() if hasattr(c, 'strip') else str(c) for c in df.columns]

            records = []
            for _, row in df.iterrows():
                # Helper to safely convert cell value to string
                def safe_str(val):
                    if pd.isna(val):
                        return ''
                    if hasattr(val, 'strip'):
                        return str(val).strip()
                    return str(val)

                sci = safe_str(row.get('IOC_15.1', ''))
                cn = safe_str(row.get('Chinese', ''))
                fam_cn = safe_str(row.get('Family', ''))
                ord_cn = safe_str(row.get('Order', ''))
                eng = safe_str(row.get('English', ''))

                if sci and sci != 'nan':
                    # Extract scientific names from IOC_15.1
                    # Example: "Acrocephalus arundinaceus" -> genus="Acrocephalus", species="arundinaceus"
                    parts = sci.split()
                    genus_sci = parts[0] if parts else ''

                    # Family and Order columns in IOC Excel are already Latin names
                    fam_sci = fam_cn  # Family column contains Latin names
                    ord_sci = ord_cn  # Order column contains Latin names

                    # Get Chinese names from mappings
                    genus_cn = genus_mapping.get(genus_sci, '') if genus_mapping else ''
                    family_cn = family_mapping.get(fam_sci, '') if family_mapping else ''
                    order_cn = order_mapping.get(ord_sci, '') if order_mapping else ''

                    # Use scientific names as fallback for Chinese names
                    final_genus_cn = genus_cn if genus_cn else genus_sci
                    final_family_cn = family_cn if family_cn else fam_sci
                    final_order_cn = order_cn if order_cn else ord_sci

                    records.append((
                        sci,        # scientific_name
                        cn,         # chinese_name
                        final_family_cn,   # family_cn
                        final_order_cn,   # order_cn
                        final_genus_cn,   # genus_cn
                        genus_sci,  # genus_sci
                        fam_sci,    # family_sci
                        ord_sci,    # order_sci
                        eng         # english_name
                    ))

            # Bulk upsert
            self.conn.executemany('''
                INSERT OR REPLACE INTO taxonomy
                (scientific_name, chinese_name, family_cn, order_cn,
                 genus_cn, genus_sci, family_sci, order_sci, english_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', records)
            self.conn.commit()
            logging.info(f"Successfully imported {len(records)} species into taxonomy.")

        except Exception as e:
            logging.error(f"Failed to import Excel: {e}")

    def get_bird_info(self, scientific_name: str) -> Optional[Dict]:
        if not scientific_name:
            return None
        try:
            with self._operation_connection() as conn:
                cursor = conn.execute("SELECT * FROM taxonomy WHERE scientific_name=?", (scientific_name,))
                row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logging.warning(f"get_bird_info failed for '{scientific_name}': {e}")
            return None

    def search_species(self, query: str, limit: int = 20) -> List[Dict]:
        q_like = f"%{query}%"
        q_start = f"{query}%"

        cursor = self.conn.execute('''
            SELECT scientific_name, chinese_name,
            CASE
                WHEN chinese_name = ? THEN 1
                WHEN chinese_name LIKE ? THEN 2
                WHEN chinese_name LIKE ? THEN 3
                ELSE 4
            END as relevance
            FROM taxonomy
            WHERE scientific_name LIKE ? OR chinese_name LIKE ?
            ORDER BY relevance ASC, LENGTH(chinese_name) ASC
            LIMIT ?
        ''', (query, q_start, q_like, q_like, q_like, limit))
        return [dict(row) for row in cursor.fetchall()]

    def get_taxonomy_tree(self, include_empty: bool = True, date_filter: str = None) -> List[Dict]:
        """
        获取完整的分类树结构（目-科-属-物种）

        Args:
            include_empty: 是否包含没有照片的层级
            date_filter: 可选日期过滤器，格式为 "YYYYMMDD"

        Returns:
            分类树列表，每个元素是一个目（Order）对象，包含其下的科、属、物种
        """
        params = []
        count_expr = "COUNT(DISTINCT p.id)"
        if date_filter:
            count_expr = "COUNT(DISTINCT CASE WHEN p.captured_date = ? THEN p.id END)"
            params.append(date_filter)

        # Step 1: Get all taxonomy data with photo counts in ONE query
        # This replaces the 12,500+ individual queries with a single efficient query
        sql = f'''
            SELECT
                t.order_cn, t.order_sci,
                t.family_cn, t.family_sci,
                t.genus_cn, t.genus_sci,
                t.scientific_name, t.chinese_name, t.english_name,
                {count_expr} as photo_count
            FROM taxonomy t
            LEFT JOIN photos p ON t.scientific_name = p.scientific_name
            WHERE t.order_cn IS NOT NULL AND t.order_cn != ''
            GROUP BY t.scientific_name
            ORDER BY t.order_cn, t.family_cn, t.genus_cn, t.chinese_name
        '''
        rows = self.conn.execute(sql, params).fetchall()

        # Step 2: Build tree structure in memory (O(n) instead of O(n*k))
        # Using dictionaries for O(1) lookup
        orders_dict = {}
        families_dict = {}
        genera_dict = {}

        for row in rows:
            order_cn = row['order_cn']
            order_sci = row['order_sci']
            family_cn = row['family_cn'] or ''
            family_sci = row['family_sci'] or ''
            genus_cn = row['genus_cn'] or ''
            genus_sci = row['genus_sci'] or ''
            sci_name = row['scientific_name']
            cn_name = row['chinese_name']
            en_name = row['english_name']
            count = row['photo_count']

            # Skip empty entries if not requested
            if not include_empty and count == 0:
                # But we still need to include species if parent has photos
                pass

            # Get or create order
            if order_cn not in orders_dict:
                orders_dict[order_cn] = {
                    'order_cn': order_cn,
                    'order_sci': order_sci,
                    'photo_count': 0,
                    'families': {}
                }
            order = orders_dict[order_cn]
            order['photo_count'] += count

            # Get or create family
            if family_cn and family_cn not in orders_dict[order_cn]['families']:
                orders_dict[order_cn]['families'][family_cn] = {
                    'family_cn': family_cn,
                    'family_sci': family_sci,
                    'photo_count': 0,
                    'genera': {}
                }
            if family_cn:
                family = orders_dict[order_cn]['families'][family_cn]
                family['photo_count'] += count

                # Get or create genus
                if genus_sci and genus_sci not in family['genera']:
                    family['genera'][genus_sci] = {
                        'genus_cn': genus_cn,
                        'genus_sci': genus_sci,
                        'photo_count': 0,
                        'species': []
                    }
                if genus_sci:
                    genus = family['genera'][genus_sci]
                    genus['photo_count'] += count
                    genus['species'].append({
                        'scientific_name': sci_name,
                        'chinese_name': cn_name,
                        'english_name': en_name,
                        'photo_count': count
                    })

        # Step 3: Convert to final structure, filtering out empty entries
        result = []
        for order_cn, order in sorted(orders_dict.items()):
            if not include_empty and order['photo_count'] == 0:
                continue

            families_data = []
            for family_cn, family in sorted(order['families'].items()):
                if not include_empty and family['photo_count'] == 0:
                    continue

                genera_data = []
                for genus_sci, genus in sorted(family['genera'].items()):
                    if not include_empty and genus['photo_count'] == 0:
                        continue

                    # Filter species: keep only those with photos or if include_empty
                    species_list = genus['species']
                    if not include_empty:
                        species_list = [sp for sp in species_list if sp['photo_count'] > 0]

                    if include_empty or species_list:
                        genus['species_count'] = len(species_list)
                        genus['species'] = species_list
                        genera_data.append(genus)

                if include_empty or genera_data:
                    family['genera_count'] = len(genera_data)
                    family['genera'] = genera_data
                    families_data.append(family)

            if include_empty or families_data:
                order['families_count'] = len(families_data)
                order['families'] = families_data
                result.append(order)

        return result

    def get_stats_by_level(self, level: str, date_filter: str = None) -> List[Dict]:
        """
        按层级统计物种数量

        Args:
            level: 'order', 'family', 'genus', 'species'
            date_filter: 可选日期过滤器，格式为 "YYYYMMDD"

        Returns:
            统计结果列表，每个元素包含名称和照片数量
        """
        date_where = ""
        params = []
        if date_filter:
            date_where = "AND p.captured_date = ?"
            params.append(date_filter)

        if level == 'order':
            sql = f'''
                SELECT DISTINCT t.order_cn as name, t.order_sci as sci, COUNT(DISTINCT p.id) as count
                FROM taxonomy t
                LEFT JOIN photos p ON t.scientific_name = p.scientific_name
                WHERE t.order_cn IS NOT NULL AND t.order_cn != ''
                {date_where}
                GROUP BY t.order_cn, t.order_sci
                ORDER BY count DESC, t.order_cn
            '''
        elif level == 'family':
            sql = f'''
                SELECT DISTINCT t.family_cn as name, t.family_sci as sci, COUNT(DISTINCT p.id) as count
                FROM taxonomy t
                LEFT JOIN photos p ON t.scientific_name = p.scientific_name
                WHERE t.family_cn IS NOT NULL AND t.family_cn != ''
                {date_where}
                GROUP BY t.family_cn, t.family_sci
                ORDER BY count DESC, t.family_cn
            '''
        elif level == 'genus':
            sql = f'''
                SELECT DISTINCT t.genus_cn as name, t.genus_sci as sci, COUNT(DISTINCT p.id) as count
                FROM taxonomy t
                LEFT JOIN photos p ON t.scientific_name = p.scientific_name
                WHERE t.genus_cn IS NOT NULL AND t.genus_cn != ''
                {date_where}
                GROUP BY t.genus_cn, t.genus_sci
                ORDER BY count DESC, t.genus_cn
            '''
        elif level == 'species':
            sql = f'''
                SELECT t.chinese_name as name, t.scientific_name as sci, COUNT(DISTINCT p.id) as count
                FROM taxonomy t
                LEFT JOIN photos p ON t.scientific_name = p.scientific_name
                {date_where}
                GROUP BY t.chinese_name, t.scientific_name
                ORDER BY count DESC, t.chinese_name
            '''
        else:
            return []

        return [dict(row) for row in self.conn.execute(sql, params)]

    def search_taxonomy(self, query: str, limit: int = 20) -> List[Dict]:
        """
        搜索分类信息（支持目、科、属、物种）

        Args:
            query: 搜索关键词
            limit: 返回结果数量限制

        Returns:
            匹配的分类信息列表，包含层级类型和匹配名称
        """
        q_like = f"%{query}%"

        # Search all levels
        results = []

        # Search orders
        cursor = self.conn.execute('''
            SELECT DISTINCT 'order' as level, order_cn as name_cn, order_sci as name_sci
            FROM taxonomy
            WHERE order_cn LIKE ?
            ORDER BY order_cn
            LIMIT ?
        ''', (q_like, limit))
        results.extend([dict(row) for row in cursor.fetchall()])

        # Search families
        cursor = self.conn.execute('''
            SELECT DISTINCT 'family' as level, family_cn as name_cn, family_sci as name_sci
            FROM taxonomy
            WHERE family_cn LIKE ?
            ORDER BY family_cn
            LIMIT ?
        ''', (q_like, limit))
        results.extend([dict(row) for row in cursor.fetchall()])

        # Search genera
        cursor = self.conn.execute('''
            SELECT DISTINCT 'genus' as level, genus_cn as name_cn, genus_sci as name_sci
            FROM taxonomy
            WHERE genus_cn LIKE ?
            ORDER BY genus_cn
            LIMIT ?
        ''', (q_like, limit))
        results.extend([dict(row) for row in cursor.fetchall()])

        # Search species (relevance-weighted)
        cursor = self.conn.execute('''
            SELECT DISTINCT 'species' as level, chinese_name as name_cn, scientific_name as name_sci,
            CASE
                WHEN chinese_name = ? THEN 1
                WHEN chinese_name LIKE ? THEN 2
                WHEN chinese_name LIKE ? THEN 3
                ELSE 4
            END as relevance
            FROM taxonomy
            WHERE chinese_name LIKE ?
            ORDER BY relevance ASC, LENGTH(chinese_name) ASC
            LIMIT ?
        ''', (query, f"{query}%", q_like, q_like, limit))
        results.extend([dict(row) for row in cursor.fetchall()])

        return results[:limit]

    def check_hash_exists(self, file_hash: str) -> bool:
        if not file_hash: return False
        with self._operation_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM photos WHERE file_hash = ? LIMIT 1", (file_hash,))
            return cursor.fetchone() is not None

    def get_all_hashes(self) -> set:
        """获取所有已处理文件的哈希集合，用于批量去重"""
        with self._operation_connection() as conn:
            cursor = conn.execute("SELECT file_hash FROM photos WHERE file_hash IS NOT NULL AND file_hash != ''")
            return {row[0] for row in cursor.fetchall()}

    def add_photo_record(self, record: Dict):
        # Convert absolute paths to relative paths for storage
        record = dict(record)
        if 'file_path' in record and record['file_path']:
            record['file_path'] = self.to_storage_processed_path(record['file_path'])
        if 'original_path' in record and record['original_path']:
            record['original_path'] = self.to_storage_original_path(record['original_path'])

        keys = ', '.join(record.keys())
        placeholders = ', '.join(['?'] * len(record))
        values = tuple(record.values())

        sql = f"INSERT INTO photos ({keys}) VALUES ({placeholders})"
        with self._operation_connection(write=True) as conn:
            cursor = conn.execute(sql, values)

            # Update species stats in the same transaction to keep photo/stat changes aligned
            if record.get('scientific_name'):
                self._update_species_stats_for_photo_conn(conn, record['scientific_name'])

            return cursor.lastrowid

    def update_photo_species(self, photo_id: int, scientific_name: str, chinese_name: str):
        with self._operation_connection(write=True) as conn:
            # Get old scientific_name before update
            cursor = conn.execute("SELECT scientific_name FROM photos WHERE id = ?", (photo_id,))
            row = cursor.fetchone()
            old_sci_name = row[0] if row else None

            conn.execute('''
                UPDATE photos
                SET scientific_name = ?, primary_bird_cn = ?, confidence_score = 1.0,
                    label_source = 'manual', manual_verified_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (scientific_name, chinese_name, photo_id))

            # Update species stats for both old and new species in the same transaction
            if old_sci_name:
                self._update_species_stats_for_photo_conn(conn, old_sci_name)
            if scientific_name:
                self._update_species_stats_for_photo_conn(conn, scientific_name)

    def add_scan_history(self, record: Dict):
        keys = ', '.join(record.keys())
        placeholders = ', '.join(['?'] * len(record))
        values = tuple(record.values())
        
        sql = f"INSERT INTO scan_history ({keys}) VALUES ({placeholders})"
        with self._operation_connection(write=True) as conn:
            conn.execute(sql, values)

    def get_recent_scans(self, limit: int = 5) -> List[Dict]:
        with self._operation_connection() as conn:
            cursor = conn.execute("SELECT * FROM scan_history ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # ========== Species Stats Table Methods ==========

    def rebuild_species_stats(self):
        """重建物种统计表（从 photos 表重新计算所有统计）"""
        logging.info("Rebuilding species stats table...")

        # Rebuild stats from photos table with taxonomy info
        sql = '''
            INSERT OR REPLACE INTO species_stats (
                scientific_name, photo_count, order_cn, order_sci,
                family_cn, family_sci, genus_cn, genus_sci,
                chinese_name, english_name, last_updated
            )
            SELECT
                t.scientific_name,
                COUNT(DISTINCT p.id) as photo_count,
                t.order_cn, t.order_sci,
                t.family_cn, t.family_sci,
                t.genus_cn, t.genus_sci,
                t.chinese_name, t.english_name,
                CURRENT_TIMESTAMP
            FROM taxonomy t
            LEFT JOIN photos p ON t.scientific_name = p.scientific_name
            GROUP BY t.scientific_name
        '''
        with self._operation_connection(write=True) as conn:
            conn.execute(sql)
        logging.info("Species stats table rebuilt")

    def update_species_stats_for_photo(self, scientific_name: str):
        """更新单个物种的统计（照片添加/修改后调用）"""
        if not scientific_name:
            return

        with self._operation_connection(write=True) as conn:
            self._update_species_stats_for_photo_conn(conn, scientific_name)

    def _update_species_stats_for_photo_conn(self, conn, scientific_name: str):
        if not scientific_name:
            return

        sql = '''
            INSERT OR REPLACE INTO species_stats (
                scientific_name, photo_count, order_cn, order_sci,
                family_cn, family_sci, genus_cn, genus_sci,
                chinese_name, english_name, last_updated
            )
            SELECT
                t.scientific_name,
                COUNT(DISTINCT p.id) as photo_count,
                t.order_cn, t.order_sci,
                t.family_cn, t.family_sci,
                t.genus_cn, t.genus_sci,
                t.chinese_name, t.english_name,
                CURRENT_TIMESTAMP
            FROM taxonomy t
            LEFT JOIN photos p ON t.scientific_name = p.scientific_name
            WHERE t.scientific_name = ?
            GROUP BY t.scientific_name
        '''
        conn.execute(sql, (scientific_name,))

    def get_species_stats_fast(self, min_count: int = 1) -> List[Dict]:
        """快速获取有照片的物种统计（从预计算表）"""
        cursor = self.conn.execute('''
            SELECT * FROM species_stats
            WHERE photo_count >= ?
            ORDER BY photo_count DESC
        ''', (min_count,))
        return [dict(row) for row in cursor.fetchall()]

    def get_taxonomy_tree_fast(self, include_empty: bool = False) -> List[Dict]:
        """使用预计算统计表的快速分类树查询"""
        # Get all stats
        stats = self.get_species_stats_fast(min_count=0 if include_empty else 1)

        # Build tree structure in memory
        orders_dict = {}
        for stat in stats:
            order_cn = stat['order_cn'] or ''
            order_sci = stat['order_sci'] or ''
            family_cn = stat['family_cn'] or ''
            family_sci = stat['family_sci'] or ''
            genus_cn = stat['genus_cn'] or ''
            genus_sci = stat['genus_sci'] or ''
            count = stat['photo_count']

            if not order_cn:
                continue

            # Get or create order
            if order_cn not in orders_dict:
                orders_dict[order_cn] = {
                    'order_cn': order_cn,
                    'order_sci': order_sci,
                    'photo_count': 0,
                    'families': {}
                }
            order = orders_dict[order_cn]
            order['photo_count'] += count

            # Get or create family
            if family_cn and family_cn not in order['families']:
                order['families'][family_cn] = {
                    'family_cn': family_cn,
                    'family_sci': family_sci,
                    'photo_count': 0,
                    'genera': {}
                }
            if family_cn:
                family = order['families'][family_cn]
                family['photo_count'] += count

                # Get or create genus
                if genus_sci and genus_sci not in family['genera']:
                    family['genera'][genus_sci] = {
                        'genus_cn': genus_cn,
                        'genus_sci': genus_sci,
                        'photo_count': 0,
                        'species': []
                    }
                if genus_sci:
                    genus = family['genera'][genus_sci]
                    genus['photo_count'] += count
                    genus['species'].append({
                        'scientific_name': stat['scientific_name'],
                        'chinese_name': stat['chinese_name'],
                        'english_name': stat['english_name'],
                        'photo_count': count
                    })

        # Convert to final structure
        result = []
        for order_cn, order in sorted(orders_dict.items()):
            if not include_empty and order['photo_count'] == 0:
                continue

            families_data = []
            for family_cn, family in sorted(order['families'].items()):
                if not include_empty and family['photo_count'] == 0:
                    continue

                genera_data = []
                for genus_sci, genus in sorted(family['genera'].items()):
                    if not include_empty and genus['photo_count'] == 0:
                        continue

                    species_list = genus['species']
                    if not include_empty:
                        species_list = [sp for sp in species_list if sp['photo_count'] > 0]

                    if include_empty or species_list:
                        genus['species_count'] = len(species_list)
                        genus['species'] = species_list
                        genera_data.append(genus)

                if include_empty or genera_data:
                    family['genera_count'] = len(genera_data)
                    family['genera'] = genera_data
                    families_data.append(family)

            if include_empty or families_data:
                order['families_count'] = len(families_data)
                order['families'] = families_data
                result.append(order)

        return result

    def close(self):
        self.conn.close()
