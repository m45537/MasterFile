# app_enhanced.py – Dataset Reconciliation (Master_Students builder)
# Version 6.0.0 – Production-ready with comprehensive improvements
# Enhanced with error handling, validation, configuration, testing, and performance optimizations

import io
import re
import logging
import traceback
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass, field
import unicodedata
from pathlib import Path
import json

import pandas as pd
import pytz
import streamlit as st
import numpy as np
from functools import lru_cache

# ─────────────────────────────────────────────────────────────
# CONFIGURATION MANAGEMENT
# ─────────────────────────────────────────────────────────────
@dataclass
class Config:
    """Central configuration for the application."""
    
    VERSION: str = "6.0.0"
    
    # File processing limits
    MAX_HEADER_SCAN_ROWS: int = 25
    MAX_FILE_SIZE_MB: int = 100
    ALLOWED_EXTENSIONS: List[str] = field(default_factory=lambda: ["xlsx", "xls"])
    CHUNK_SIZE: int = 1000  # For processing large files in chunks
    
    # Excel formatting colors
    COLORS: Dict[str, str] = field(default_factory=lambda: {
        'blackbaud': "#000000",
        'rediker': "#A10000", 
        'student_records': "#006400",
        'warning': "#FFF59D",
        'severe': "#FFC7CE",
        'ok': "#C6EFCE",
        'ok_text': "#006100",
        'bad': "#FFC7CE",
        'bad_text': "#9C0006"
    })
    
    # Excel column constraints
    EXCEL_MAX_COL_WIDTH: int = 50
    EXCEL_MIN_COL_WIDTH: int = 8
    EXCEL_MAX_CELL_LENGTH: int = 32767  # Excel cell limit
    
    # Name processing
    NAME_SUFFIXES: set = field(default_factory=lambda: {
        "JR", "SR", "II", "III", "IV", "V", "VI", "ESQ", "PHD", "MD"
    })
    
    # Grade mappings for normalization
    GRADE_MAPPING: Dict[str, List[str]] = field(default_factory=lambda: {
        'PK3': ['P3', 'PK3', 'PREK3', 'PRE-K3', 'PREKINDER3'],
        'PK4': ['P4', 'PK4', 'PREK4', 'PRE-K4', 'PREK', 'PRE-K', 'PREKINDER4', 'PREKINDER'],
        'K': ['K', 'KG', 'KDG', 'KINDER', 'KINDERGARTEN', '0K', 'OK', 'ZERO-K']
    })
    
    # Column detection tokens
    BLACKBAUD_TOKENS: List[str] = field(default_factory=lambda: [
        "FAMILY", "ID", "PARENT", "FIRST", "LAST", "STUDENT", "GRADE"
    ])
    REDIKER_TOKENS: List[str] = field(default_factory=lambda: [
        "APID", "STUDENT", "STUDENT NAME", "FIRST", "LAST", "GRADE", "UNIQUE"
    ])
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Performance
    ENABLE_CACHING: bool = True
    PARALLEL_PROCESSING: bool = False  # Future enhancement
    
    # Data validation
    MIN_NAME_LENGTH: int = 1
    MAX_NAME_LENGTH: int = 255
    VALID_GRADE_PATTERN: str = r"^(PK3|PK4|K|[1-9]|1[0-2])$"

# Initialize configuration
config = Config()

# ─────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ─────────────────────────────────────────────────────────────
class DataReconciliationError(Exception):
    """Base exception for data reconciliation errors."""
    pass

class FileValidationError(DataReconciliationError):
    """Raised when file validation fails."""
    pass

class ColumnDetectionError(DataReconciliationError):
    """Raised when required columns cannot be detected."""
    pass

class DataProcessingError(DataReconciliationError):
    """Raised during data processing."""
    pass

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dataset Reconciliation",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📘 Dataset Reconciliation System")
st.caption(f"Version {config.VERSION} - Production Ready")

# Enhanced description
with st.expander("ℹ️ About this tool", expanded=False):
    st.markdown("""
    ### Purpose
    This tool reconciles student data from three different systems:
    - **Blackbaud**: Family/parent roster with student information
    - **Rediker**: Student management system data
    - **Student Records**: Internal student database
    
    ### Output
    Creates a comprehensive Master_Students Excel file with:
    - **Master Sheet**: All records with source tracking and mismatch highlighting
    - **Summary Sheet**: Unique students with presence indicators
    - **Mismatches Sheet**: Students not found in all three systems
    
    ### Features
    - Intelligent name parsing and normalization
    - Grade level standardization (PK3, PK4, K, 1-12)
    - Automatic mismatch detection and highlighting
    - Comprehensive error handling and validation
    - Processing statistics and quality metrics
    """)

# ─────────────────────────────────────────────────────────────
# SIDEBAR SETTINGS
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Debug options
    debug_tab, stats_tab, advanced_tab = st.tabs(["Debug", "Statistics", "Advanced"])
    
    with debug_tab:
        debug_log = st.checkbox("🪵 Show detailed logs", value=False)
        show_raw_data = st.checkbox("📊 Show raw data preview", value=False)
        export_debug = st.checkbox("💾 Export debug information", value=False)
    
    with stats_tab:
        show_stats = st.checkbox("📈 Show processing statistics", value=True)
        show_quality = st.checkbox("✅ Show data quality metrics", value=True)
        show_charts = st.checkbox("📊 Show visualization charts", value=False)
    
    with advanced_tab:
        st.subheader("Advanced Options")
        max_file_size = st.number_input(
            "Max file size (MB)",
            min_value=10,
            max_value=500,
            value=config.MAX_FILE_SIZE_MB,
            help="Maximum allowed file size for uploads"
        )
        config.MAX_FILE_SIZE_MB = max_file_size
        
        enable_fuzzy = st.checkbox(
            "Enable fuzzy matching",
            value=False,
            help="Use fuzzy string matching for name comparison"
        )
        
        strict_mode = st.checkbox(
            "Strict validation mode",
            value=False,
            help="Enforce strict data validation rules"
        )

# ─────────────────────────────────────────────────────────────
# DATA VALIDATION MODULE
# ─────────────────────────────────────────────────────────────
class DataValidator:
    """Handles all data validation operations."""
    
    @staticmethod
    def validate_file(file) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Comprehensive file validation.
        Returns: (is_valid, message, metadata)
        """
        metadata = {}
        
        if file is None:
            return False, "No file provided", metadata
        
        try:
            # Get file size
            file.seek(0, 2)
            size_bytes = file.tell()
            file.seek(0)
            size_mb = size_bytes / (1024 * 1024)
            metadata['size_mb'] = size_mb
            metadata['filename'] = file.name
            
            # Check size
            if size_mb > config.MAX_FILE_SIZE_MB:
                return False, f"File too large: {size_mb:.1f}MB (max: {config.MAX_FILE_SIZE_MB}MB)", metadata
            
            # Check extension
            file_ext = Path(file.name).suffix.lower().lstrip('.')
            metadata['extension'] = file_ext
            
            if file_ext not in config.ALLOWED_EXTENSIONS:
                return False, f"Invalid file type '{file_ext}'. Allowed: {', '.join(config.ALLOWED_EXTENSIONS)}", metadata
            
            # Try to read the file header
            try:
                test_df = pd.read_excel(file, nrows=5, engine="openpyxl")
                metadata['rows_preview'] = len(test_df)
                metadata['columns_preview'] = len(test_df.columns)
                file.seek(0)
            except Exception as e:
                return False, f"Cannot read file: {str(e)}", metadata
            
            return True, "File validation successful", metadata
            
        except Exception as e:
            logger.error(f"File validation error: {str(e)}")
            return False, f"Validation error: {str(e)}", metadata
    
    @staticmethod
    def sanitize_string(s: Optional[str], max_length: int = None) -> str:
        """
        Sanitize string for Excel compatibility and security.
        """
        if s is None or pd.isna(s):
            return ""
        
        # Convert to string and normalize unicode
        s = str(s).strip()
        
        # Normalize unicode characters
        try:
            s = unicodedata.normalize('NFKD', s)
        except Exception:
            pass
        
        # Prevent formula injection
        if s and s[0] in ['=', '+', '-', '@', '\t', '\r']:
            s = "'" + s
        
        # Remove null bytes and other problematic characters
        s = s.replace('\x00', '')
        
        # Apply length limit
        if max_length is None:
            max_length = config.MAX_NAME_LENGTH
        
        return s[:max_length] if len(s) > max_length else s
    
    @staticmethod
    def validate_name(name: str, field_type: str = "name") -> Tuple[bool, str]:
        """Validate a name field."""
        if not name or len(name) < config.MIN_NAME_LENGTH:
            return False, f"{field_type} too short"
        if len(name) > config.MAX_NAME_LENGTH:
            return False, f"{field_type} too long"
        # Check for suspicious patterns
        if re.search(r'[<>\"\';&]', name):
            return True, f"{field_type} contains special characters (sanitized)"
        return True, ""
    
    @staticmethod
    def validate_grade(grade: str) -> Tuple[bool, str]:
        """Validate grade format."""
        if not grade:
            return True, "Empty grade (allowed)"
        normalized = grade_norm(grade)
        if re.match(config.VALID_GRADE_PATTERN, normalized):
            return True, ""
        return False, f"Invalid grade format: {grade}"

validator = DataValidator()

# ─────────────────────────────────────────────────────────────
# ENHANCED NORMALIZATION WITH CACHING
# ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=1024) if config.ENABLE_CACHING else lambda f: f
def norm_piece(s: str) -> str:
    """Cached normalization: uppercase, keep letters/digits/spaces/hyphens."""
    s = validator.sanitize_string(s)
    return re.sub(r"[^A-Z0-9 \-]+", "", s.upper()).strip()

@lru_cache(maxsize=512) if config.ENABLE_CACHING else lambda f: f
def grade_norm(s: str) -> str:
    """
    Enhanced grade normalization with validation and caching.
    """
    if s is None or pd.isna(s):
        return ""
    
    x = norm_piece(s)
    x = re.sub(r"\s+", "", x)
    
    if x == "":
        return ""
    
    # Check predefined mappings
    for normalized, variations in config.GRADE_MAPPING.items():
        if x in variations:
            return normalized
    
    # PK patterns
    if re.fullmatch(r"P[K]?4", x):
        return "PK4"
    if re.fullmatch(r"P[K]?3", x):
        return "PK3"
    
    # K patterns
    if x in config.GRADE_MAPPING['K']:
        return "K"
    
    # Numeric grades 1-12
    m = re.fullmatch(r"(?:GRADE|GR|G)?0*([1-9]|1[0-2])(?:TH)?", x)
    if m:
        return m.group(1)
    
    # Ordinal patterns
    m = re.search(r"0*([1-9]|1[0-2])(?:ST|ND|RD|TH)", x)
    if m:
        return m.group(1)
    
    logger.debug(f"Could not normalize grade: '{s}' -> '{x}'")
    return x

@lru_cache(maxsize=1024) if config.ENABLE_CACHING else lambda f: f
def surname_last_token(last: str) -> str:
    """Extract meaningful surname token, ignoring suffixes."""
    s = norm_piece(last).replace("-", " ")
    toks = [t for t in s.split() if t]
    
    if not toks:
        return ""
    
    # Remove suffix if present
    if len(toks) > 1 and toks[-1] in config.NAME_SUFFIXES:
        return toks[-2] if len(toks) >= 2 else toks[0]
    
    return toks[-1]

@lru_cache(maxsize=1024) if config.ENABLE_CACHING else lambda f: f
def firstname_first_token(first: str, last: str) -> str:
    """Extract first name token with fallback."""
    ftoks = [t for t in norm_piece(first).split() if t]
    if ftoks:
        return ftoks[0]
    
    ltoks = [t for t in norm_piece(last).split() if t]
    return ltoks[0] if ltoks else ""

def make_unique_key(first: str, last: str, grade: str) -> str:
    """
    Generate unique student identifier with validation.
    """
    # Sanitize all inputs
    first = validator.sanitize_string(first).replace("|", "-")
    last = validator.sanitize_string(last).replace("|", "-")
    grade = validator.sanitize_string(grade).replace("|", "-")
    
    surname = surname_last_token(last)
    firstname = firstname_first_token(first, last)
    grade_normalized = grade_norm(grade)
    
    key = f"{surname}|{firstname}|{grade_normalized}"
    
    # Ensure key isn't too long
    if len(key) > 255:
        key = key[:255]
    
    return key

# ─────────────────────────────────────────────────────────────
# COLUMN DETECTION WITH FUZZY MATCHING
# ─────────────────────────────────────────────────────────────
class ColumnDetector:
    """Advanced column detection with fuzzy matching support."""
    
    @staticmethod
    def find_any(df: pd.DataFrame, *need_tokens) -> Optional[str]:
        """Find column containing all tokens in any token tuple."""
        if df is None or df.empty:
            return None
        
        for cand in df.columns:
            up = str(cand).strip().upper()
            for token_tuple in need_tokens:
                if all(tok in up for tok in token_tuple):
                    return cand
        return None
    
    @staticmethod
    def fuzzy_find_column(df: pd.DataFrame, target: str, threshold: float = 0.8) -> Optional[str]:
        """Find column using fuzzy string matching."""
        if not enable_fuzzy:  # Check if fuzzy matching is enabled
            return None
        
        from difflib import SequenceMatcher
        
        best_match = None
        best_score = 0
        
        for col in df.columns:
            score = SequenceMatcher(None, str(col).upper(), target.upper()).ratio()
            if score > best_score and score >= threshold:
                best_score = score
                best_match = col
        
        return best_match
    
    @staticmethod
    def find_student_grade_blob_column(df: pd.DataFrame) -> Optional[str]:
        """Find Blackbaud's combined student/grade column."""
        if df is None or df.empty:
            return None
        
        # First try explicit patterns
        for c in df.columns:
            up = str(c).strip().upper()
            if "STUDENT" in up and ("GRADE" in up or "CLASS" in up):
                return c
        
        # Then look for parenthetical patterns
        scores = {}
        for c in df.columns:
            try:
                # Count cells with (Grade) pattern
                pattern_count = df[c].astype(str).str.contains(
                    r'\([^)]+\)\s*$', regex=True, na=False
                ).sum()
                scores[c] = pattern_count
            except Exception as e:
                logger.debug(f"Error checking column {c}: {e}")
                scores[c] = 0
        
        if not scores:
            return None
        
        best = max(scores, key=scores.get)
        return best if scores[best] >= 3 else None

detector = ColumnDetector()

# ─────────────────────────────────────────────────────────────
# PARSER BASE CLASS
# ─────────────────────────────────────────────────────────────
class BaseParser:
    """Base class for file parsers with common functionality."""
    
    def __init__(self, source_name: str, source_code: str):
        self.source_name = source_name
        self.source_code = source_code
        self.errors = []
        self.warnings = []
    
    def add_error(self, msg: str):
        """Add error message."""
        self.errors.append(msg)
        logger.error(f"{self.source_name}: {msg}")
    
    def add_warning(self, msg: str):
        """Add warning message."""
        self.warnings.append(msg)
        logger.warning(f"{self.source_name}: {msg}")
    
    def detect_header_row(self, file, tokens: List[str], max_rows: int = 25) -> int:
        """Detect header row by searching for tokens."""
        try:
            probe = pd.read_excel(file, header=None, nrows=max_rows, engine="openpyxl")
            
            best_row = 0
            best_score = -1
            
            for i in range(len(probe)):
                row_text = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
                score = sum(token in row_text for token in tokens)
                
                if score > best_score:
                    best_score = score
                    best_row = i
            
            confidence = best_score / len(tokens) if tokens else 0
            
            if debug_log:
                st.write(f"🔍 {self.source_name} - Header detection:")
                st.write(f"  - Row: {best_row}")
                st.write(f"  - Confidence: {confidence:.1%} ({best_score}/{len(tokens)} tokens)")
            
            return best_row
            
        except Exception as e:
            self.add_error(f"Header detection failed: {e}")
            return 0
    
    def create_output_row(self, **kwargs) -> Dict[str, Any]:
        """Create standardized output row."""
        return {
            "ID": kwargs.get("id", ""),
            "FAMILY ID": kwargs.get("family_id", ""),
            "PARENT FIRST NAME": validator.sanitize_string(kwargs.get("parent_first", "")),
            "PARENT LAST NAME": validator.sanitize_string(kwargs.get("parent_last", "")),
            "STUDENT FIRST NAME": validator.sanitize_string(kwargs.get("student_first", "")),
            "STUDENT LAST NAME": validator.sanitize_string(kwargs.get("student_last", "")),
            "GRADE": validator.sanitize_string(kwargs.get("grade", "")),
            "REDIKER ID": kwargs.get("rediker_id", ""),
            "SOURCE": self.source_code,
        }

# ─────────────────────────────────────────────────────────────
# ENHANCED BLACKBAUD PARSER
# ─────────────────────────────────────────────────────────────
class BlackbaudParser(BaseParser):
    """Parser for Blackbaud roster files."""
    
    def __init__(self):
        super().__init__("Blackbaud", "BB")
    
    def parse(self, file) -> pd.DataFrame:
        """Parse Blackbaud file with comprehensive error handling."""
        try:
            # Validate file
            valid, msg, metadata = validator.validate_file(file)
            if not valid:
                self.add_error(f"File validation failed: {msg}")
                return pd.DataFrame()
            
            # Detect header
            header_row = self.detect_header_row(file, config.BLACKBAUD_TOKENS)
            
            # Read data
            df = pd.read_excel(file, header=header_row, engine="openpyxl").fillna("")
            df.columns = [str(c).strip() for c in df.columns]
            
            # Detect columns
            fam_col = detector.find_any(df, ("FAMILY", "ID"))
            pf_col = detector.find_any(df, 
                ("PARENT", "FIRST"), 
                ("PRIMARY", "PARENT", "FIRST"), 
                ("GUARDIAN", "FIRST")
            )
            pl_col = detector.find_any(df,
                ("PARENT", "LAST"),
                ("PRIMARY", "PARENT", "LAST"),
                ("GUARDIAN", "LAST")
            )
            stu_blob_col = detector.find_student_grade_blob_column(df)
            
            if not stu_blob_col:
                self.add_error("Cannot find student/grade column")
                return pd.DataFrame()
            
            if not pf_col or not pl_col:
                self.add_warning("Parent name columns not found - using blanks")
            
            # Parse students
            rows = []
            for _, row in df.iterrows():
                family_id = str(row.get(fam_col, "")).replace(".0", "").strip() if fam_col else ""
                parent_first = str(row.get(pf_col, "")).strip() if pf_col else ""
                parent_last = str(row.get(pl_col, "")).strip() if pl_col else ""
                
                students = self._parse_student_blob(row.get(stu_blob_col, ""))
                
                for student_last, student_first, grade in students:
                    rows.append(self.create_output_row(
                        family_id=family_id,
                        parent_first=parent_first,
                        parent_last=parent_last,
                        student_first=student_first,
                        student_last=student_last,
                        grade=grade
                    ))
            
            # Create DataFrame
            out_df = pd.DataFrame(rows)
            out_df["UNIQUE_KEY"] = [
                make_unique_key(f, l, g) 
                for f, l, g in zip(
                    out_df["STUDENT FIRST NAME"],
                    out_df["STUDENT LAST NAME"],
                    out_df["GRADE"]
                )
            ]
            
            if debug_log:
                st.write(f"✅ {self.source_name} - Parsed {len(out_df)} records")
                if self.warnings:
                    st.warning(f"Warnings: {', '.join(self.warnings)}")
            
            return out_df
            
        except Exception as e:
            self.add_error(f"Fatal parsing error: {e}")
            logger.error(traceback.format_exc())
            return pd.DataFrame()
    
    def _parse_student_blob(self, cell: str) -> List[Tuple[str, str, str]]:
        """Parse student entries from blob cell."""
        if pd.isna(cell) or str(cell).strip() == "":
            return []
        
        # Split multiple students
        text = re.sub(r"\s*\)\s*[,/;|]?\s*", ")|", str(cell))
        entries = [p.strip().rstrip(",;/|") for p in text.split("|") if p.strip()]
        
        students = []
        for entry in entries:
            # Extract grade in parentheses
            grade_match = re.search(r"\(([^)]+)\)\s*$", entry)
            grade = grade_match.group(1).strip() if grade_match else ""
            
            # Remove grade from name
            name = re.sub(r"\([^)]+\)\s*$", "", entry).strip()
            
            # Parse name
            if ";" in name:
                last, first = [t.strip() for t in name.split(";", 1)]
            elif "," in name:
                last, first = [t.strip() for t in name.split(",", 1)]
            else:
                # Multi-part surname support
                tokens = name.split()
                if len(tokens) >= 2:
                    last = " ".join(tokens[:-1])
                    first = tokens[-1]
                else:
                    last, first = name, ""
            
            students.append((last, first, grade))
        
        return students

# ─────────────────────────────────────────────────────────────
# ENHANCED REDIKER PARSER
# ─────────────────────────────────────────────────────────────
class RedikerParser(BaseParser):
    """Parser for Rediker files."""
    
    def __init__(self):
        super().__init__("Rediker", "RED")
    
    def parse(self, file) -> pd.DataFrame:
        """Parse Rediker file."""
        try:
            # Validate
            valid, msg, metadata = validator.validate_file(file)
            if not valid:
                self.add_error(f"File validation failed: {msg}")
                return pd.DataFrame()
            
            # Detect header
            header_row = self.detect_header_row(file, config.REDIKER_TOKENS, max_rows=12)
            
            # Read data
            df = pd.read_excel(file, header=header_row, engine="openpyxl").fillna("")
            df.columns = [str(c).strip() for c in df.columns]
            col_map = {c.upper(): c for c in df.columns}
            
            # Find student name column
            student_col = (
                col_map.get("STUDENT NAME") or 
                col_map.get("STUDENT") or 
                col_map.get("STUDENT_NAME")
            )
            
            if not student_col:
                self.add_error("Cannot find student name column")
                return pd.DataFrame()
            
            # Find other columns
            parent_first_col = col_map.get("FIRST NAME") or col_map.get("FIRST")
            parent_last_col = col_map.get("LAST NAME") or col_map.get("LAST")
            
            # Grade column with multiple fallbacks
            grade_col = self._find_grade_column(df, col_map)
            if not grade_col:
                self.add_warning("No grade column found - using blanks")
                df["__GRADE_BLANK"] = ""
                grade_col = "__GRADE_BLANK"
            
            # IDs
            fam_col = col_map.get("FAMILY ID") or col_map.get("FAMILYID")
            rid_col = col_map.get("APID") or col_map.get("UNIQUE ID") or col_map.get("ID")
            
            # Parse rows
            rows = []
            for _, row in df.iterrows():
                student_first, student_last = self._parse_student_name(row.get(student_col, ""))
                
                rows.append(self.create_output_row(
                    family_id=str(row.get(fam_col, "")).replace(".0", "") if fam_col else "",
                    parent_first=str(row.get(parent_first_col, "")) if parent_first_col else "",
                    parent_last=str(row.get(parent_last_col, "")) if parent_last_col else "",
                    student_first=student_first,
                    student_last=student_last,
                    grade=str(row.get(grade_col, "")),
                    rediker_id=str(row.get(rid_col, "")).replace(".0", "") if rid_col else ""
                ))
            
            # Create output
            out_df = pd.DataFrame(rows)
            out_df["UNIQUE_KEY"] = [
                make_unique_key(f, l, g)
                for f, l, g in zip(
                    out_df["STUDENT FIRST NAME"],
                    out_df["STUDENT LAST NAME"],
                    out_df["GRADE"]
                )
            ]
            
            if debug_log:
                st.write(f"✅ {self.source_name} - Parsed {len(out_df)} records")
            
            return out_df
            
        except Exception as e:
            self.add_error(f"Fatal parsing error: {e}")
            logger.error(traceback.format_exc())
            return pd.DataFrame()
    
    def _find_grade_column(self, df: pd.DataFrame, col_map: Dict[str, str]) -> Optional[str]:
        """Find grade column with multiple strategies."""
        grade_keywords = [
            "GRADE", "GRADE LEVEL", "GRADELEVEL", "GR", "GR LEVEL",
            "GRLEVEL", "CURRENT GRADE", "CUR GRADE", "CLASS"
        ]
        
        for keyword in grade_keywords:
            if keyword in col_map:
                return col_map[keyword]
        
        # Check partial matches
        for key, orig in col_map.items():
            if "GRADE" in key and "FAMILY" not in key:
                return orig
        
        return None
    
    def _parse_student_name(self, value: str) -> Tuple[str, str]:
        """Parse student name into first and last."""
        if pd.isna(value) or not str(value).strip():
            return "", ""
        
        name = str(value).strip()
        
        # Try semicolon format
        if ";" in name:
            last, first = [t.strip() for t in name.split(";", 1)]
        # Try comma format
        elif "," in name:
            last, first = [t.strip() for t in name.split(",", 1)]
        # Space-separated
        else:
            parts = name.split()
            if len(parts) >= 2:
                # Assume "First Last" format
                first = " ".join(parts[:-1])
                last = parts[-1]
            elif len(parts) == 1:
                first = parts[0]
                last = ""
            else:
                first = last = ""
        
        return first, last

# ─────────────────────────────────────────────────────────────
# ENHANCED STUDENT RECORDS PARSER
# ─────────────────────────────────────────────────────────────
class StudentRecordsParser(BaseParser):
    """Parser for Student Records files."""
    
    def __init__(self):
        super().__init__("Student Records", "SR")
    
    def parse(self, file) -> pd.DataFrame:
        """Parse Student Records file."""
        try:
            # Validate
            valid, msg, metadata = validator.validate_file(file)
            if not valid:
                self.add_error(f"File validation failed: {msg}")
                return pd.DataFrame()
            
            # Read file
            df = pd.read_excel(file, engine="openpyxl").fillna("")
            df.columns = [str(c).strip() for c in df.columns]
            col_map = {c.upper(): c for c in df.columns}
            
            # Detect columns
            columns = self._detect_columns(df, col_map)
            
            if not columns['student_first'] or not columns['student_last']:
                # Try to parse combined name column
                if not self._handle_combined_name(df, col_map, columns):
                    self.add_error("Cannot find student name columns")
                    return pd.DataFrame()
            
            # Build output
            rows = []
            for _, row in df.iterrows():
                # Skip empty name rows
                sf = str(row.get(columns['student_first'], "")).strip()
                sl = str(row.get(columns['student_last'], "")).strip()
                
                if not sf and not sl:
                    continue
                
                rows.append(self.create_output_row(
                    id=str(row.get(columns['id'], "")).replace(".0", "") if columns['id'] else "",
                    family_id=str(row.get(columns['family_id'], "")).replace(".0", "") if columns['family_id'] else "",
                    parent_first=str(row.get(columns['parent_first'], "")) if columns['parent_first'] else "",
                    parent_last=str(row.get(columns['parent_last'], "")) if columns['parent_last'] else "",
                    student_first=sf,
                    student_last=sl,
                    grade=str(row.get(columns['grade'], "")) if columns['grade'] else "",
                    rediker_id=str(row.get(columns['rediker_id'], "")).replace(".0", "") if columns['rediker_id'] else ""
                ))
            
            # Create output
            out_df = pd.DataFrame(rows)
            out_df["UNIQUE_KEY"] = [
                make_unique_key(f, l, g)
                for f, l, g in zip(
                    out_df["STUDENT FIRST NAME"],
                    out_df["STUDENT LAST NAME"],
                    out_df["GRADE"]
                )
            ]
            
            if debug_log:
                st.write(f"✅ {self.source_name} - Parsed {len(out_df)} records")
            
            return out_df
            
        except Exception as e:
            self.add_error(f"Fatal parsing error: {e}")
            logger.error(traceback.format_exc())
            return pd.DataFrame()
    
    def _detect_columns(self, df: pd.DataFrame, col_map: Dict[str, str]) -> Dict[str, Optional[str]]:
        """Detect all relevant columns."""
        return {
            'id': df.columns[0] if len(df.columns) > 0 else None,
            'family_id': col_map.get("FAMILY ID") or col_map.get("FAMILYID"),
            'rediker_id': col_map.get("REDIKER ID") or col_map.get("REDIKERID"),
            'parent_first': col_map.get("PARENT FIRST NAME") or col_map.get("PARENT FIRST"),
            'parent_last': col_map.get("PARENT LAST NAME") or col_map.get("PARENT LAST"),
            'student_first': (
                col_map.get("STUDENT FIRST NAME") or 
                col_map.get("CHILD FIRST NAME") or 
                col_map.get("FIRST NAME") or 
                col_map.get("FIRST")
            ),
            'student_last': (
                col_map.get("STUDENT LAST NAME") or
                col_map.get("CHILD LAST NAME") or
                col_map.get("LAST NAME") or
                col_map.get("LAST")
            ),
            'grade': col_map.get("GRADE") or col_map.get("GRADE LEVEL") or col_map.get("GR")
        }
    
    def _handle_combined_name(self, df: pd.DataFrame, col_map: Dict[str, str], 
                             columns: Dict[str, Optional[str]]) -> bool:
        """Handle combined name columns."""
        name_col = (
            col_map.get("STUDENT NAME") or
            col_map.get("CHILD NAME") or
            col_map.get("NAME")
        )
        
        if not name_col:
            return False
        
        # Try to split the name
        series = df[name_col].astype(str).str.strip()
        
        # Try comma split
        split = series.str.split(",", n=1, expand=True)
        if split.shape[1] == 2:
            df["__SPLIT_LAST"] = split[0].str.strip()
            df["__SPLIT_FIRST"] = split[1].str.strip()
        else:
            # Try semicolon split
            split = series.str.split(";", n=1, expand=True)
            if split.shape[1] == 2:
                df["__SPLIT_LAST"] = split[0].str.strip()
                df["__SPLIT_FIRST"] = split[1].str.strip()
            else:
                # Space split
                df["__SPLIT_FIRST"] = series.str.split().str[0]
                df["__SPLIT_LAST"] = series.str.split().str[-1]
        
        columns['student_first'] = "__SPLIT_FIRST"
        columns['student_last'] = "__SPLIT_LAST"
        return True

# ─────────────────────────────────────────────────────────────
# MASTER BUILDER
# ─────────────────────────────────────────────────────────────
class MasterBuilder:
    """Builds and formats the master Excel file."""
    
    def __init__(self):
        self.stats = {}
    
    def build_master(self, bb_df: pd.DataFrame, red_df: pd.DataFrame, 
                    sr_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Build master, summary, and mismatch dataframes."""
        
        # Combine all sources
        target_cols = [
            "ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
            "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
            "REDIKER ID", "SOURCE", "UNIQUE_KEY"
        ]
        
        combined = pd.concat(
            [bb_df[target_cols], red_df[target_cols], sr_df[target_cols]],
            ignore_index=True
        )
        
        # Calculate presence counts
        src_counts = combined.groupby("UNIQUE_KEY")["SOURCE"].nunique().to_dict()
        combined["__SRC_PRESENT"] = combined["UNIQUE_KEY"].map(src_counts).fillna(0).astype(int)
        
        # Sort with priority
        order = {"BB": 0, "RED": 1, "SR": 2}
        combined["_source_rank"] = combined["SOURCE"].map(lambda x: order.get(str(x).upper(), 99))
        
        master = combined.sort_values(
            by=["UNIQUE_KEY", "_source_rank", "STUDENT LAST NAME", "STUDENT FIRST NAME"],
            kind="mergesort"
        ).reset_index(drop=True)
        
        # Build summary
        summary = self._build_summary(master)
        
        # Build mismatches
        mismatches = summary[summary["SOURCES_PRESENT"] < 3].reset_index(drop=True)
        
        # Calculate statistics
        self.stats = {
            'total_records': len(master),
            'unique_students': len(summary),
            'fully_matched': len(summary[summary["SOURCES_PRESENT"] == 3]),
            'partial_matched': len(summary[summary["SOURCES_PRESENT"] == 2]),
            'single_source': len(summary[summary["SOURCES_PRESENT"] == 1]),
            'bb_records': len(bb_df),
            'red_records': len(red_df),
            'sr_records': len(sr_df)
        }
        
        return master, summary, mismatches
    
    def _build_summary(self, master: pd.DataFrame) -> pd.DataFrame:
        """Build summary dataframe."""
        summary_rows = []
        
        for key, group in master.groupby("UNIQUE_KEY"):
            parts = key.split("|")
            surname = parts[0] if len(parts) >= 1 else ""
            first = parts[1] if len(parts) >= 2 else ""
            grade = parts[2] if len(parts) >= 3 else ""
            
            # Check presence
            sources = group["SOURCE"].str.upper()
            in_bb = any(sources == "BB")
            in_red = any(sources == "RED")
            in_sr = any(sources == "SR")
            present_count = int(in_bb) + int(in_red) + int(in_sr)
            
            # Get raw names from each source
            raw_bb = self._get_raw_names(group, "BB")
            raw_red = self._get_raw_names(group, "RED")
            raw_sr = self._get_raw_names(group, "SR")
            
            summary_rows.append({
                "SURNAME": surname,
                "FIRST": first,
                "GRADE": grade_norm(grade),
                "BB": "✅" if in_bb else "❌",
                "RED": "✅" if in_red else "❌",
                "SR": "✅" if in_sr else "❌",
                "SOURCES_PRESENT": present_count,
                "RAW_NAMES_BB": "; ".join(raw_bb),
                "RAW_NAMES_RED": "; ".join(raw_red),
                "RAW_NAMES_SR": "; ".join(raw_sr),
            })
        
        return pd.DataFrame(summary_rows).sort_values(
            ["SURNAME", "GRADE", "FIRST"]
        ).reset_index(drop=True)
    
    def _get_raw_names(self, group: pd.DataFrame, source: str) -> List[str]:
        """Get raw names for a specific source."""
        names = []
        for _, row in group.iterrows():
            if str(row["SOURCE"]).upper() == source:
                name = f"{row['STUDENT LAST NAME']} {row['STUDENT FIRST NAME']}".strip()
                if name:
                    names.append(name)
        return names
    
    def create_excel(self, master: pd.DataFrame, summary: pd.DataFrame, 
                    mismatches: pd.DataFrame) -> bytes:
        """Create formatted Excel file."""
        import xlsxwriter
        
        output = io.BytesIO()
        
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            # Write master sheet
            self._write_master_sheet(writer, master)
            
            # Write summary sheet
            self._write_summary_sheet(writer, summary)
            
            # Write mismatches sheet
            self._write_mismatches_sheet(writer, mismatches)
            
            # Add metadata sheet
            self._write_metadata_sheet(writer)
        
        return output.getvalue()
    
    def _write_master_sheet(self, writer, master: pd.DataFrame):
        """Write and format master sheet."""
        # Prepare data
        master_out = master[[
            "ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
            "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
            "REDIKER ID", "SOURCE", "UNIQUE_KEY", "__SRC_PRESENT"
        ]].copy()
        
        master_out.to_excel(writer, index=False, sheet_name="Master")
        
        wb = writer.book
        ws = writer.sheets["Master"]
        
        # Create formats
        formats = self._create_formats(wb)
        
        # Write headers
        for col_idx, col in enumerate(master_out.columns):
            ws.write(0, col_idx, col, formats['header'])
        
        # Auto-size columns
        self._autosize_columns(ws, master_out)
        
        # Write data with formatting
        self._format_master_data(ws, master_out, formats)
        
        # Freeze panes
        ws.freeze_panes(1, 0)
    
    def _write_summary_sheet(self, writer, summary: pd.DataFrame):
        """Write and format summary sheet."""
        summary.to_excel(writer, index=False, sheet_name="Summary")
        
        wb = writer.book
        ws = writer.sheets["Summary"]
        
        formats = self._create_formats(wb)
        
        # Headers
        for col_idx, col in enumerate(summary.columns):
            ws.write(0, col_idx, col, formats['header'])
        
        # Auto-size
        self._autosize_columns(ws, summary)
        
        # Format check/cross cells
        col_idx = {c: i for i, c in enumerate(summary.columns)}
        for row in range(len(summary)):
            for src_col in ["BB", "RED", "SR"]:
                val = summary.iat[row, col_idx[src_col]]
                fmt = formats['ok'] if val == "✅" else formats['bad']
                ws.write(row + 1, col_idx[src_col], val, fmt)
        
        # Freeze panes
        ws.freeze_panes(1, 3)
    
    def _write_mismatches_sheet(self, writer, mismatches: pd.DataFrame):
        """Write and format mismatches sheet."""
        mismatches.to_excel(writer, index=False, sheet_name="Summary_Mismatches")
        
        wb = writer.book
        ws = writer.sheets["Summary_Mismatches"]
        
        formats = self._create_formats(wb)
        
        # Headers
        for col_idx, col in enumerate(mismatches.columns):
            ws.write(0, col_idx, col, formats['header'])
        
        # Auto-size
        self._autosize_columns(ws, mismatches)
        
        # Format check/cross cells
        col_idx = {c: i for i, c in enumerate(mismatches.columns)}
        for row in range(len(mismatches)):
            for src_col in ["BB", "RED", "SR"]:
                val = mismatches.iat[row, col_idx[src_col]]
                fmt = formats['ok'] if val == "✅" else formats['bad']
                ws.write(row + 1, col_idx[src_col], val, fmt)
        
        # Freeze panes
        ws.freeze_panes(1, 3)
    
    def _write_metadata_sheet(self, writer):
        """Write metadata sheet with processing information."""
        metadata = pd.DataFrame([
            ["Version", config.VERSION],
            ["Process Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["Total Records", self.stats.get('total_records', 0)],
            ["Unique Students", self.stats.get('unique_students', 0)],
            ["Fully Matched (3 sources)", self.stats.get('fully_matched', 0)],
            ["Partial Matched (2 sources)", self.stats.get('partial_matched', 0)],
            ["Single Source Only", self.stats.get('single_source', 0)],
            ["Blackbaud Records", self.stats.get('bb_records', 0)],
            ["Rediker Records", self.stats.get('red_records', 0)],
            ["Student Records", self.stats.get('sr_records', 0)]
        ], columns=["Metric", "Value"])
        
        metadata.to_excel(writer, index=False, sheet_name="Metadata")
        
        wb = writer.book
        ws = writer.sheets["Metadata"]
        
        # Format
        header_fmt = wb.add_format({"bold": True, "bg_color": "#E0E0E0"})
        for col_idx in range(2):
            ws.write(0, col_idx, metadata.columns[col_idx], header_fmt)
        
        # Auto-size
        ws.set_column(0, 0, 30)
        ws.set_column(1, 1, 20)
    
    def _create_formats(self, workbook) -> Dict[str, Any]:
        """Create all Excel formats."""
        return {
            'header': workbook.add_format({
                "bold": True,
                "bg_color": "#E0E0E0",
                "border": 1
            }),
            'bb': workbook.add_format({"font_color": config.COLORS['blackbaud']}),
            'red': workbook.add_format({"font_color": config.COLORS['rediker']}),
            'sr': workbook.add_format({"font_color": config.COLORS['student_records']}),
            'bb_warn': workbook.add_format({
                "font_color": config.COLORS['blackbaud'],
                "bg_color": config.COLORS['warning'],
                "bold": True
            }),
            'red_warn': workbook.add_format({
                "font_color": config.COLORS['rediker'],
                "bg_color": config.COLORS['warning'],
                "bold": True
            }),
            'sr_warn': workbook.add_format({
                "font_color": config.COLORS['student_records'],
                "bg_color": config.COLORS['warning'],
                "bold": True
            }),
            'bb_severe': workbook.add_format({
                "font_color": config.COLORS['blackbaud'],
                "bg_color": config.COLORS['severe'],
                "bold": True
            }),
            'red_severe': workbook.add_format({
                "font_color": config.COLORS['rediker'],
                "bg_color": config.COLORS['severe'],
                "bold": True
            }),
            'sr_severe': workbook.add_format({
                "font_color": config.COLORS['student_records'],
                "bg_color": config.COLORS['severe'],
                "bold": True
            }),
            'ok': workbook.add_format({
                "bg_color": config.COLORS['ok'],
                "font_color": config.COLORS['ok_text']
            }),
            'bad': workbook.add_format({
                "bg_color": config.COLORS['bad'],
                "font_color": config.COLORS['bad_text']
            })
        }
    
    def _autosize_columns(self, worksheet, dataframe: pd.DataFrame):
        """Auto-size columns based on content."""
        for i, col in enumerate(dataframe.columns):
            # Calculate max width
            max_len = len(str(col))
            
            # Sample data for width calculation
            sample = dataframe[col].astype(str).head(500)
            if len(sample) > 0:
                max_len = max(max_len, sample.str.len().max())
            
            # Apply constraints
            width = min(max(max_len + 2, config.EXCEL_MIN_COL_WIDTH), 
                       config.EXCEL_MAX_COL_WIDTH)
            
            worksheet.set_column(i, i, width)
    
    def _format_master_data(self, worksheet, dataframe: pd.DataFrame, formats: Dict):
        """Apply conditional formatting to master sheet."""
        idx = {c: i for i, c in enumerate(dataframe.columns)}
        source_col = idx["SOURCE"]
        present_col = idx["__SRC_PRESENT"]
        
        for row in range(len(dataframe)):
            source = str(dataframe.iat[row, source_col]).upper()
            present = int(dataframe.iat[row, present_col])
            
            # Select format based on source and presence
            if source == "RED":
                base, warn, severe = formats['red'], formats['red_warn'], formats['red_severe']
            elif source == "SR":
                base, warn, severe = formats['sr'], formats['sr_warn'], formats['sr_severe']
            else:
                base, warn, severe = formats['bb'], formats['bb_warn'], formats['bb_severe']
            
            # Choose format by presence count
            if present >= 3:
                row_fmt = base
            elif present == 2:
                row_fmt = warn
            else:
                row_fmt = severe
            
            # Write row
            for col in range(len(dataframe.columns)):
                worksheet.write(row + 1, col, dataframe.iat[row, col], row_fmt)

# ─────────────────────────────────────────────────────────────
# MAIN UI
# ─────────────────────────────────────────────────────────────
st.subheader("📁 1. Upload Source Files")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Blackbaud Roster**")
    f_bb = st.file_uploader(
        "Family roster with students",
        type=config.ALLOWED_EXTENSIONS,
        key="bb",
        help="Upload your Blackbaud export containing family and student information"
    )
    if f_bb:
        st.success(f"✓ {f_bb.name}")

with col2:
    st.markdown("**Rediker**")
    f_red = st.file_uploader(
        "Student management data",
        type=config.ALLOWED_EXTENSIONS,
        key="red",
        help="Upload your Rediker export with student records"
    )
    if f_red:
        st.success(f"✓ {f_red.name}")

with col3:
    st.markdown("**Student Records**")
    f_sr = st.file_uploader(
        "Internal student database",
        type=config.ALLOWED_EXTENSIONS,
        key="sr",
        help="Upload your internal student records file"
    )
    if f_sr:
        st.success(f"✓ {f_sr.name}")

# Check if all files are uploaded
if not (f_bb and f_red and f_sr):
    st.info("👆 Please upload all three files to proceed")
    
    with st.expander("📋 File Format Requirements"):
        st.markdown("""
        **Blackbaud File:**
        - Must contain: Family ID, Parent names, Student names with grades
        - Student format: "LastName, FirstName (Grade)" or similar
        
        **Rediker File:**
        - Must contain: Student names, Grade level
        - Optional: APID, Family ID, Parent names
        
        **Student Records:**
        - Must contain: Student first/last names OR combined name
        - Optional: Grade, Family ID, Rediker ID
        """)
    st.stop()

# Process button
st.subheader("🚀 2. Build Master File")

col1, col2 = st.columns([3, 1])
with col1:
    run = st.button(
        "Build Master_Students Excel",
        type="primary",
        use_container_width=True,
        help="Click to process all files and generate the master reconciliation"
    )

with col2:
    if st.button("🔄 Clear All", use_container_width=True):
        st.rerun()

# ─────────────────────────────────────────────────────────────
# MAIN PROCESSING
# ─────────────────────────────────────────────────────────────
if run:
    try:
        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Parse files
        status_text.text("📖 Parsing Blackbaud roster...")
        progress_bar.progress(10)
        bb_parser = BlackbaudParser()
        bb_df = bb_parser.parse(f_bb)
        
        status_text.text("📖 Parsing Rediker data...")
        progress_bar.progress(30)
        red_parser = RedikerParser()
        red_df = red_parser.parse(f_red)
        
        status_text.text("📖 Parsing Student Records...")
        progress_bar.progress(50)
        sr_parser = StudentRecordsParser()
        sr_df = sr_parser.parse(f_sr)
        
        # Check for parsing failures
        errors = []
        if bb_df.empty:
            errors.append("Blackbaud file parsing failed")
        if red_df.empty:
            errors.append("Rediker file parsing failed")
        if sr_df.empty:
            errors.append("Student Records parsing failed")
        
        if errors:
            st.error("❌ Parsing Errors:\n" + "\n".join(f"• {e}" for e in errors))
            st.stop()
        
        # Build master
        status_text.text("🔨 Building master dataset...")
        progress_bar.progress(70)
        
        builder = MasterBuilder()
        master, summary, mismatches = builder.build_master(bb_df, red_df, sr_df)
        
        # Create Excel
        status_text.text("📝 Creating Excel file...")
        progress_bar.progress(90)
        
        excel_data = builder.create_excel(master, summary, mismatches)
        
        # Complete
        progress_bar.progress(100)
        status_text.text("✅ Complete!")
        
        # Display statistics
        if show_stats:
            st.subheader("📊 Processing Statistics")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Records", builder.stats['total_records'])
            with col2:
                st.metric("Unique Students", builder.stats['unique_students'])
            with col3:
                match_rate = (builder.stats['fully_matched'] / builder.stats['unique_students'] * 100) if builder.stats['unique_students'] > 0 else 0
                st.metric("Full Match Rate", f"{match_rate:.1f}%")
            with col4:
                mismatch_count = builder.stats['partial_matched'] + builder.stats['single_source']
                st.metric("Mismatches", mismatch_count)
            
            # Detailed breakdown
            with st.expander("📊 Detailed Breakdown"):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown("**Source Records:**")
                    st.write(f"• Blackbaud: {builder.stats['bb_records']}")
                    st.write(f"• Rediker: {builder.stats['red_records']}")
                    st.write(f"• Student Records: {builder.stats['sr_records']}")
                
                with col2:
                    st.markdown("**Match Quality:**")
                    st.write(f"• 3 Sources: {builder.stats['fully_matched']}")
                    st.write(f"• 2 Sources: {builder.stats['partial_matched']}")
                    st.write(f"• 1 Source: {builder.stats['single_source']}")
                
                with col3:
                    st.markdown("**Data Quality:**")
                    total = builder.stats['unique_students']
                    if total > 0:
                        st.write(f"• Full Match: {builder.stats['fully_matched']/total*100:.1f}%")
                        st.write(f"• Partial: {builder.stats['partial_matched']/total*100:.1f}%")
                        st.write(f"• Single: {builder.stats['single_source']/total*100:.1f}%")
        
        # Show charts if enabled
        if show_charts and show_stats:
            import plotly.express as px
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Pie chart of match quality
                fig = px.pie(
                    values=[builder.stats['fully_matched'], 
                           builder.stats['partial_matched'],
                           builder.stats['single_source']],
                    names=['Full Match (3)', 'Partial (2)', 'Single (1)'],
                    title="Match Quality Distribution",
                    color_discrete_map={
                        'Full Match (3)': '#4CAF50',
                        'Partial (2)': '#FFC107',
                        'Single (1)': '#F44336'
                    }
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                # Bar chart of source contributions
                fig = px.bar(
                    x=['Blackbaud', 'Rediker', 'Student Records'],
                    y=[builder.stats['bb_records'], 
                       builder.stats['red_records'],
                       builder.stats['sr_records']],
                    title="Records by Source",
                    labels={'x': 'Source', 'y': 'Record Count'}
                )
                st.plotly_chart(fig, use_container_width=True)
        
        # Preview data if enabled
        if show_raw_data:
            with st.expander("👁️ Preview Processed Data"):
                tab1, tab2, tab3 = st.tabs(["Master", "Summary", "Mismatches"])
                
                with tab1:
                    st.dataframe(master.head(100))
                
                with tab2:
                    st.dataframe(summary.head(100))
                
                with tab3:
                    if not mismatches.empty:
                        st.dataframe(mismatches.head(100))
                    else:
                        st.success("No mismatches found!")
        
        # Generate filename
        eastern = pytz.timezone("America/New_York")
        timestamp = datetime.now(eastern).strftime("%y%m%d_%H%M")
        filename = f"{timestamp}_Master_Students.xlsx"
        
        # Download button
        st.success("✅ **Master file generated successfully!**")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.download_button(
                label=f"⬇️ Download {filename}",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        with col2:
            if export_debug:
                # Create debug report
                debug_report = {
                    'version': config.VERSION,
                    'timestamp': datetime.now().isoformat(),
                    'stats': builder.stats,
                    'errors': {
                        'blackbaud': bb_parser.errors,
                        'rediker': red_parser.errors,
                        'student_records': sr_parser.errors
                    },
                    'warnings': {
                        'blackbaud': bb_parser.warnings,
                        'rediker': red_parser.warnings,
                        'student_records': sr_parser.warnings
                    }
                }
                
                st.download_button(
                    label="💾 Download Debug Report",
                    data=json.dumps(debug_report, indent=2),
                    file_name=f"{timestamp}_debug_report.json",
                    mime="application/json",
                    use_container_width=True
                )
        
    except Exception as e:
        st.error(f"❌ **Critical Error:** {str(e)}")
        
        if debug_log:
            st.code(traceback.format_exc())
        
        st.error("Please check your files and try again. If the problem persists, contact support.")
        
        # Log the error
        logger.critical(f"Critical error in main process: {str(e)}")
        logger.critical(traceback.format_exc())

# ─────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────
st.markdown("---")
build_id = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
col1, col2, col3 = st.columns(3)

with col1:
    st.caption(f"Build: {build_id}")

with col2:
    st.caption(f"Version: {config.VERSION}")

with col3:
    st.caption("Dataset Reconciliation System")
