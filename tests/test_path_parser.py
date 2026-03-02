import pytest
from pathlib import Path
from src.core.io.path_parser import PathParser

class TestPathParserRecursive:
    
    def setup_method(self):
        self.root = "D:/data/raw"
        self.parser = PathParser(self.root)

    def test_basic_existing_behavior(self):
        # Existing: 20231020_OlympicPark -> OlympicPark
        path = f"{self.root}/20231020_OlympicPark/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['location_tag'] == 'OlympicPark'
        assert meta['captured_date'] == '20231020'

    def test_new_range_full_year(self):
        # 20231001-20231007Japan -> Japan
        path = f"{self.root}/20231001-20231007Japan/bird.jpg"
        meta = self.parser.parse(path)
        # Note: logic might change to support recursion, but for single level it should match
        assert meta['location_tag'] == 'Japan' 

    def test_new_range_short_day(self):
        # 20231001-07_USA -> USA
        path = f"{self.root}/20231001-07_USA/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['location_tag'] == 'USA'
        assert meta['captured_date'] == '20231001'

    def test_recursive_location(self):
        # Parent: 20231001-07_USA
        # Child: NYC
        # Expected: USA_NYC
        path = f"{self.root}/20231001-07_USA/NYC/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['location_tag'] == 'USA_NYC'

    def test_recursive_deep(self):
        # Parent: 20231001-07_China
        # Child: Beijing
        # Child: SummerPalace
        # Expected: China_Beijing_SummerPalace
        path = f"{self.root}/20231001-07_China/Beijing/SummerPalace/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['location_tag'] == 'China_Beijing_SummerPalace'

    def test_mixed_patterns(self):
        # Parent: 20230101-20230201_Trip
        # Child: 20230105_CityA (Nested date pattern?)
        # Let's assume nested folders might just be locations, or also have dates.
        # If nested has date, maybe we update date? But user mainly cares about location prefix.
        path = f"{self.root}/20230101-20230201_Trip/20230105_CityA/bird.jpg"
        meta = self.parser.parse(path)
        assert 'Trip' in meta['location_tag']
        assert 'CityA' in meta['location_tag']
        # Exact format depends on implementation choice, e.g. "Trip_CityA"
        assert meta['location_tag'] == 'Trip_CityA'
        # Date should probably reflect the file's immediate context if available?
        # Or keep the root? Usually immediate context is better.
        assert meta['captured_date'] == '20230105' 

    def test_user_specific_example(self):
        # Example: 20241228-20250105日本游\20241230东京台场滨海公园
        path = f"{self.root}/20241228-20250105日本游/20241230东京台场滨海公园/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['captured_date'] == '20241230'
        # Current implementation joins with _
        assert meta['location_tag'] == '日本游_东京台场滨海公园'

    def test_auto_mode_compatibility(self):
        # Simulating how Auto mode checks the string
        location_tag = "Japan_Tokyo"
        foreign_countries = ["Japan", "USA"]

        is_foreign = False
        for country in foreign_countries:
            if country in location_tag:
                is_foreign = True
                break
        assert is_foreign is True

    def test_year_directory_should_be_skipped(self):
        # Bug 27: 年份目录（如 2025）不应被当作地点的一部分
        # 结构: 2025/北京柳荫公园/bird.jpg
        # 预期: location_tag = "北京柳荫公园" (不含年份)
        path = f"{self.root}/2025/北京柳荫公园/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['location_tag'] == '北京柳荫公园'
        # 日期应该来自文件名或其他方式（当前没有日期信息）

    def test_year_directory_with_date_subfolder(self):
        # 结构: 2025/20260110_北京柳荫公园/bird.jpg
        # 预期: location_tag = "北京柳荫公园", captured_date = "20260110"
        path = f"{self.root}/2025/20260110_北京柳荫公园/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['location_tag'] == '北京柳荫公园'
        assert meta['captured_date'] == '20260110'

    def test_multiple_year_directories(self):
        # 结构: 2025/2026/北京柳荫公园/bird.jpg
        # 预期: 跳过所有年份目录，location_tag = "北京柳荫公园"
        path = f"{self.root}/2025/2026/北京柳荫公园/bird.jpg"
        meta = self.parser.parse(path)
        assert meta['location_tag'] == '北京柳荫公园'
