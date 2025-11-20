"""
test_app_enhanced.py - Comprehensive test suite for Dataset Reconciliation
Run with: python -m pytest test_app_enhanced.py -v
"""

import unittest
import pandas as pd
import numpy as np
from io import BytesIO
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import functions to test (mock the streamlit parts)
import streamlit as st
st.cache_data = lambda f: f  # Mock decorator

from app_enhanced import (
    Config, DataValidator, norm_piece, grade_norm, 
    surname_last_token, firstname_first_token, make_unique_key,
    ColumnDetector, BlackbaudParser, RedikerParser, 
    StudentRecordsParser, MasterBuilder
)


class TestConfiguration(unittest.TestCase):
    """Test configuration management."""
    
    def test_config_initialization(self):
        """Test that configuration initializes with correct defaults."""
        config = Config()
        self.assertEqual(config.VERSION, "6.0.0")
        self.assertEqual(config.MAX_FILE_SIZE_MB, 100)
        self.assertIn("xlsx", config.ALLOWED_EXTENSIONS)
        self.assertIn("JR", config.NAME_SUFFIXES)
    
    def test_color_configuration(self):
        """Test color configuration."""
        config = Config()
        self.assertEqual(config.COLORS['blackbaud'], "#000000")
        self.assertEqual(config.COLORS['warning'], "#FFF59D")
        self.assertEqual(config.COLORS['severe'], "#FFC7CE")


class TestDataValidation(unittest.TestCase):
    """Test data validation functions."""
    
    def setUp(self):
        self.validator = DataValidator()
    
    def test_sanitize_string(self):
        """Test string sanitization."""
        # Test normal string
        self.assertEqual(self.validator.sanitize_string("Hello"), "Hello")
        
        # Test formula injection prevention
        self.assertEqual(self.validator.sanitize_string("=SUM(A1:A10)"), "'=SUM(A1:A10)")
        self.assertEqual(self.validator.sanitize_string("+1234"), "'+1234")
        
        # Test null/None handling
        self.assertEqual(self.validator.sanitize_string(None), "")
        self.assertEqual(self.validator.sanitize_string(np.nan), "")
        
        # Test length limiting
        long_string = "A" * 500
        result = self.validator.sanitize_string(long_string, max_length=255)
        self.assertEqual(len(result), 255)
    
    def test_validate_name(self):
        """Test name validation."""
        # Valid names
        valid, msg = self.validator.validate_name("John", "first name")
        self.assertTrue(valid)
        
        valid, msg = self.validator.validate_name("O'Brien", "last name")
        self.assertTrue(valid)
        
        # Empty name
        valid, msg = self.validator.validate_name("", "name")
        self.assertFalse(valid)
        
        # Too long name
        long_name = "A" * 300
        valid, msg = self.validator.validate_name(long_name, "name")
        self.assertFalse(valid)
    
    def test_validate_grade(self):
        """Test grade validation."""
        # Valid grades
        valid, _ = self.validator.validate_grade("PK4")
        self.assertTrue(valid)
        
        valid, _ = self.validator.validate_grade("K")
        self.assertTrue(valid)
        
        valid, _ = self.validator.validate_grade("12")
        self.assertTrue(valid)
        
        # Empty grade (allowed)
        valid, _ = self.validator.validate_grade("")
        self.assertTrue(valid)


class TestNormalization(unittest.TestCase):
    """Test normalization functions."""
    
    def test_norm_piece(self):
        """Test basic normalization."""
        self.assertEqual(norm_piece("Hello World"), "HELLO WORLD")
        self.assertEqual(norm_piece("Test-123"), "TEST-123")
        self.assertEqual(norm_piece("Special@#$Characters"), "SPECIALCHARACTERS")
        self.assertEqual(norm_piece("  spaces  "), "SPACES")
        self.assertEqual(norm_piece(None), "")
    
    def test_grade_norm(self):
        """Test grade normalization."""
        # PK variations
        self.assertEqual(grade_norm("PRE-K4"), "PK4")
        self.assertEqual(grade_norm("PREK4"), "PK4")
        self.assertEqual(grade_norm("P4"), "PK4")
        self.assertEqual(grade_norm("PK3"), "PK3")
        
        # Kindergarten variations
        self.assertEqual(grade_norm("K"), "K")
        self.assertEqual(grade_norm("KG"), "K")
        self.assertEqual(grade_norm("KINDERGARTEN"), "K")
        self.assertEqual(grade_norm("0K"), "K")
        
        # Numeric grades
        self.assertEqual(grade_norm("1"), "1")
        self.assertEqual(grade_norm("01"), "1")
        self.assertEqual(grade_norm("1st"), "1")
        self.assertEqual(grade_norm("GRADE 4"), "4")
        self.assertEqual(grade_norm("4TH"), "4")
        self.assertEqual(grade_norm("12"), "12")
        self.assertEqual(grade_norm("12th"), "12")
        
        # Edge cases
        self.assertEqual(grade_norm(""), "")
        self.assertEqual(grade_norm(None), "")
    
    def test_surname_last_token(self):
        """Test surname extraction."""
        self.assertEqual(surname_last_token("Smith"), "SMITH")
        self.assertEqual(surname_last_token("Van Der Berg"), "BERG")
        self.assertEqual(surname_last_token("Smith Jr"), "SMITH")
        self.assertEqual(surname_last_token("Johnson III"), "JOHNSON")
        self.assertEqual(surname_last_token("Mary-Jane"), "MARY JANE")
        self.assertEqual(surname_last_token(""), "")
    
    def test_firstname_first_token(self):
        """Test first name extraction."""
        self.assertEqual(firstname_first_token("John", "Doe"), "JOHN")
        self.assertEqual(firstname_first_token("Mary Jane", "Smith"), "MARY")
        self.assertEqual(firstname_first_token("", "Doe"), "DOE")
        self.assertEqual(firstname_first_token("", ""), "")
    
    def test_make_unique_key(self):
        """Test unique key generation."""
        key = make_unique_key("John", "Smith", "4")
        self.assertEqual(key, "SMITH|JOHN|4")
        
        key = make_unique_key("Mary Jane", "Van Der Berg Jr", "PRE-K4")
        self.assertEqual(key, "BERG|MARY|PK4")
        
        # Test pipe sanitization
        key = make_unique_key("John|Test", "Smith|Test", "4")
        self.assertNotIn("||", key)


class TestColumnDetection(unittest.TestCase):
    """Test column detection functionality."""
    
    def setUp(self):
        self.detector = ColumnDetector()
    
    def test_find_any(self):
        """Test column finding with token matching."""
        df = pd.DataFrame(columns=["Student First Name", "Parent Last Name", "Grade Level"])
        
        # Should find columns
        col = self.detector.find_any(df, ("STUDENT", "FIRST"))
        self.assertEqual(col, "Student First Name")
        
        col = self.detector.find_any(df, ("PARENT", "LAST"))
        self.assertEqual(col, "Parent Last Name")
        
        # Should not find
        col = self.detector.find_any(df, ("TEACHER", "NAME"))
        self.assertIsNone(col)
    
    def test_find_student_grade_blob(self):
        """Test finding combined student/grade column."""
        # Create test data
        data = {
            "Family ID": ["F001", "F002"],
            "Students (Grade)": ["Smith, John (4)", "Doe, Jane (K)"],
            "Other Column": ["Data1", "Data2"]
        }
        df = pd.DataFrame(data)
        
        col = self.detector.find_student_grade_blob_column(df)
        self.assertEqual(col, "Students (Grade)")


class TestParsers(unittest.TestCase):
    """Test file parsers."""
    
    def test_blackbaud_student_blob_parsing(self):
        """Test parsing of Blackbaud student blob format."""
        parser = BlackbaudParser()
        
        # Test various formats
        students = parser._parse_student_blob("Smith, John (4)")
        self.assertEqual(students, [("Smith", "John", "4")])
        
        students = parser._parse_student_blob("Smith, John (4); Doe, Jane (K)")
        self.assertEqual(len(students), 2)
        self.assertIn(("Smith", "John", "4"), students)
        self.assertIn(("Doe", "Jane", "K"), students)
        
        # Test without grade
        students = parser._parse_student_blob("Smith John")
        self.assertEqual(students, [("Smith", "John", "")])
    
    def test_rediker_name_parsing(self):
        """Test Rediker name parsing."""
        parser = RedikerParser()
        
        # Comma format
        first, last = parser._parse_student_name("Smith, John")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")
        
        # Semicolon format
        first, last = parser._parse_student_name("Smith; John")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")
        
        # Space format
        first, last = parser._parse_student_name("John Smith")
        self.assertEqual(first, "John")
        self.assertEqual(last, "Smith")
        
        # Empty
        first, last = parser._parse_student_name("")
        self.assertEqual(first, "")
        self.assertEqual(last, "")


class TestMasterBuilder(unittest.TestCase):
    """Test master builder functionality."""
    
    def setUp(self):
        self.builder = MasterBuilder()
    
    def create_sample_data(self):
        """Create sample dataframes for testing."""
        # Common columns
        cols = ["ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
                "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
                "REDIKER ID", "SOURCE", "UNIQUE_KEY"]
        
        # Blackbaud data
        bb_data = pd.DataFrame([
            ["", "F001", "John", "Doe", "Jane", "Doe", "4", "", "BB", "DOE|JANE|4"],
            ["", "F002", "Bob", "Smith", "Tim", "Smith", "K", "", "BB", "SMITH|TIM|K"]
        ], columns=cols)
        
        # Rediker data
        red_data = pd.DataFrame([
            ["", "F001", "", "", "Jane", "Doe", "4", "R001", "RED", "DOE|JANE|4"],
            ["", "F003", "", "", "Sally", "Jones", "2", "R003", "RED", "JONES|SALLY|2"]
        ], columns=cols)
        
        # Student Records data
        sr_data = pd.DataFrame([
            ["S001", "F001", "John", "Doe", "Jane", "Doe", "4", "R001", "SR", "DOE|JANE|4"],
            ["S002", "F002", "Bob", "Smith", "Tim", "Smith", "K", "R002", "SR", "SMITH|TIM|K"]
        ], columns=cols)
        
        return bb_data, red_data, sr_data
    
    def test_build_master(self):
        """Test building master dataset."""
        bb_df, red_df, sr_df = self.create_sample_data()
        
        master, summary, mismatches = self.builder.build_master(bb_df, red_df, sr_df)
        
        # Check master has all records
        self.assertEqual(len(master), 6)  # 2 BB + 2 RED + 2 SR
        
        # Check summary
        self.assertEqual(len(summary), 3)  # 3 unique students
        
        # Check mismatches
        self.assertEqual(len(mismatches), 1)  # Sally Jones only in RED
        
        # Check statistics
        self.assertEqual(self.builder.stats['total_records'], 6)
        self.assertEqual(self.builder.stats['unique_students'], 3)
        self.assertEqual(self.builder.stats['fully_matched'], 1)  # Jane Doe
    
    def test_summary_creation(self):
        """Test summary creation logic."""
        bb_df, red_df, sr_df = self.create_sample_data()
        
        master, summary, _ = self.builder.build_master(bb_df, red_df, sr_df)
        
        # Find Jane Doe in summary (should be in all 3 sources)
        jane = summary[summary["SURNAME"] == "DOE"]
        self.assertEqual(len(jane), 1)
        self.assertEqual(jane.iloc[0]["BB"], "✅")
        self.assertEqual(jane.iloc[0]["RED"], "✅")
        self.assertEqual(jane.iloc[0]["SR"], "✅")
        self.assertEqual(jane.iloc[0]["SOURCES_PRESENT"], 3)
        
        # Find Sally Jones (only in RED)
        sally = summary[summary["SURNAME"] == "JONES"]
        self.assertEqual(len(sally), 1)
        self.assertEqual(sally.iloc[0]["BB"], "❌")
        self.assertEqual(sally.iloc[0]["RED"], "✅")
        self.assertEqual(sally.iloc[0]["SR"], "❌")
        self.assertEqual(sally.iloc[0]["SOURCES_PRESENT"], 1)


class TestExcelGeneration(unittest.TestCase):
    """Test Excel file generation."""
    
    def test_excel_creation(self):
        """Test that Excel file is created successfully."""
        builder = MasterBuilder()
        
        # Create sample data
        cols = ["ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
                "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
                "REDIKER ID", "SOURCE", "UNIQUE_KEY"]
        
        bb_df = pd.DataFrame([
            ["", "F001", "John", "Doe", "Jane", "Doe", "4", "", "BB", "DOE|JANE|4"]
        ], columns=cols)
        
        red_df = pd.DataFrame([
            ["", "F001", "", "", "Jane", "Doe", "4", "R001", "RED", "DOE|JANE|4"]
        ], columns=cols)
        
        sr_df = pd.DataFrame([
            ["S001", "F001", "John", "Doe", "Jane", "Doe", "4", "R001", "SR", "DOE|JANE|4"]
        ], columns=cols)
        
        # Build master
        master, summary, mismatches = builder.build_master(bb_df, red_df, sr_df)
        
        # Create Excel
        excel_data = builder.create_excel(master, summary, mismatches)
        
        # Check that we got bytes
        self.assertIsInstance(excel_data, bytes)
        self.assertGreater(len(excel_data), 0)
        
        # Try to read it back
        excel_file = BytesIO(excel_data)
        sheets = pd.read_excel(excel_file, sheet_name=None, engine="openpyxl")
        
        # Check sheets exist
        self.assertIn("Master", sheets)
        self.assertIn("Summary", sheets)
        self.assertIn("Summary_Mismatches", sheets)
        self.assertIn("Metadata", sheets)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""
    
    def test_empty_dataframes(self):
        """Test handling of empty dataframes."""
        builder = MasterBuilder()
        
        cols = ["ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
                "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
                "REDIKER ID", "SOURCE", "UNIQUE_KEY"]
        
        empty_df = pd.DataFrame(columns=cols)
        
        master, summary, mismatches = builder.build_master(empty_df, empty_df, empty_df)
        
        self.assertEqual(len(master), 0)
        self.assertEqual(len(summary), 0)
        self.assertEqual(len(mismatches), 0)
    
    def test_special_characters_in_names(self):
        """Test handling of special characters."""
        # Test apostrophes
        key = make_unique_key("John", "O'Brien", "4")
        self.assertIn("OBRIEN", key)
        
        # Test hyphens
        key = make_unique_key("Mary-Jane", "Smith-Jones", "K")
        self.assertIn("MARY", key)
        self.assertIn("SMITH", key)
    
    def test_unicode_characters(self):
        """Test handling of unicode characters."""
        validator = DataValidator()
        
        # Test accented characters
        sanitized = validator.sanitize_string("Café")
        self.assertIsInstance(sanitized, str)
        
        sanitized = validator.sanitize_string("Müller")
        self.assertIsInstance(sanitized, str)
        
        sanitized = validator.sanitize_string("北京")
        self.assertIsInstance(sanitized, str)
    
    def test_grade_edge_cases(self):
        """Test grade normalization edge cases."""
        # Invalid grades should pass through
        result = grade_norm("13")
        self.assertEqual(result, "13")
        
        result = grade_norm("INVALID")
        self.assertEqual(result, "INVALID")
        
        # Mixed case and spacing
        self.assertEqual(grade_norm("pre k 4"), "PK4")
        self.assertEqual(grade_norm("GRADE12"), "12")


class TestPerformance(unittest.TestCase):
    """Test performance with larger datasets."""
    
    def test_large_dataset_processing(self):
        """Test processing of larger datasets."""
        # Create larger sample data
        n_records = 1000
        
        cols = ["ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
                "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
                "REDIKER ID", "SOURCE", "UNIQUE_KEY"]
        
        data = []
        for i in range(n_records):
            grade = str((i % 12) + 1)
            unique_key = f"LASTNAME{i}|FIRSTNAME{i}|{grade}"
            data.append([
                f"ID{i}", f"F{i:04d}", f"Parent{i}", f"LastName{i}",
                f"FirstName{i}", f"LastName{i}", grade, f"R{i:04d}",
                "BB", unique_key
            ])
        
        df = pd.DataFrame(data, columns=cols)
        
        # Process
        builder = MasterBuilder()
        master, summary, mismatches = builder.build_master(df, df, df)
        
        # Check results
        self.assertEqual(len(master), n_records * 3)
        self.assertEqual(len(summary), n_records)
        self.assertEqual(len(mismatches), 0)  # All should match


if __name__ == '__main__':
    unittest.main(verbosity=2)
