# app_improved.py – Dataset Reconciliation (Master_Students builder)
# Version 5.3.0 – Enhanced with error handling, validation, and configuration

import io
import re
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
import unicodedata

import pandas as pd
import pytz
import streamlit as st

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────
@dataclass
class Config:
    VERSION = "5.3.0"
    
    # File processing
    MAX_HEADER_SCAN_ROWS = 25
    MAX_FILE_SIZE_MB = 100
    ALLOWED_EXTENSIONS = ["xlsx", "xls"]
    
    # Excel formatting
    COLORS = {
        'blackbaud': "#000000",
        'rediker': "#A10000", 
        'student_records': "#006400",
        'warning': "#FFF59D",
        'severe': "#FFC7CE",
        'ok': "#C6EFCE",
        'ok_text': "#006100",
        'bad': "#FFC7CE",
        'bad_text': "#9C0006"
    }
    
    EXCEL_MAX_COL_WIDTH = 50
    EXCEL_MIN_COL_WIDTH = 8
    
    # Data processing
    NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "VI"}
    GRADE_MAPPING = {
        'PK3': ['P3', 'PK3', 'PREK3', 'PRE-K3'],
        'PK4': ['P4', 'PK4', 'PREK4', 'PRE-K4', 'PREK', 'PRE-K'],
        'K': ['K', 'KG', 'KDG', 'KINDER', 'KINDERGARTEN', '0K', 'OK']
    }

# Initialize configuration
config = Config()

# ─────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Dataset Reconciliation", page_icon="📘", layout="centered")

st.title("📘 Dataset Reconciliation")
st.caption(f"Version {config.VERSION}")
st.caption(
    "Upload Blackbaud Roster, Rediker, and Student Records → builds a Master_Students Excel "
    "with a detailed Master sheet and two Summary sheets (all + mismatches)."
)

# Sidebar – debug toggle
with st.sidebar:
    debug_log = st.checkbox("🪵 Show detailed debug logs", value=False)
    show_stats = st.checkbox("📊 Show processing statistics", value=False)
    st.caption("When enabled, shows header detection, column choices, and sample parsed rows.")

# ─────────────────────────────────────────────────────────────
# ENHANCED NORMALIZATION HELPERS
# ─────────────────────────────────────────────────────────────
def sanitize_string(s: Optional[str], max_length: int = 255) -> str:
    """Sanitize string for Excel compatibility."""
    if s is None or pd.isna(s):
        return ""
    
    # Convert to string and normalize unicode
    s = str(s).strip()
    s = unicodedata.normalize('NFKD', s)
    
    # Remove potential formula injection characters at start
    if s and s[0] in ['=', '+', '-', '@']:
        s = "'" + s
    
    # Truncate if too long
    return s[:max_length] if len(s) > max_length else s

def norm_piece(s: str) -> str:
    """Uppercase, keep letters/digits/spaces/hyphens, strip."""
    s = sanitize_string(s)
    return re.sub(r"[^A-Z0-9 \-]+", "", s.upper()).strip()

def grade_norm(s: str) -> str:
    """
    Enhanced grade normalization with validation.
    """
    if s is None:
        return ""

    x = norm_piece(s)
    x = re.sub(r"\s+", "", x)
    if x == "":
        return ""

    # Check grade mappings
    for normalized, variations in config.GRADE_MAPPING.items():
        if x in variations:
            return normalized

    # PK4 patterns
    if re.fullmatch(r"P[K]?4", x):
        return "PK4"

    # PK3 patterns  
    if re.fullmatch(r"P[K]?3", x):
        return "PK3"

    # Grades 1–12
    m = re.fullmatch(r"(?:GRADE|GR|G)?0*([1-9]|1[0-2])", x)
    if m:
        return m.group(1)

    m = re.search(r"0*([1-9]|1[0-2])(ST|ND|RD|TH)?", x)
    if m:
        return m.group(1)

    logger.warning(f"Could not normalize grade: {s} -> {x}")
    return x

def surname_last_token(last: str) -> str:
    """
    Use the last "real" surname token (ignoring JR, SR, II, etc).
    """
    s = norm_piece(last).replace("-", " ")
    toks = [t for t in s.split() if t]
    if not toks:
        return ""
    
    if toks[-1] in config.NAME_SUFFIXES and len(toks) >= 2:
        return toks[-2]
    return toks[-1]

def firstname_first_token(first: str, last: str) -> str:
    """
    Prefer first token of FIRST name; if missing, fall back to first token of LAST.
    """
    ftoks = [t for t in norm_piece(first).split() if t]
    if ftoks:
        return ftoks[0]
    ltoks = [t for t in norm_piece(last).split() if t]
    return ltoks[0] if ltoks else ""

def make_unique_key(first: str, last: str, grade: str) -> str:
    """
    Student identity key used across datasets with validation.
    """
    # Sanitize inputs
    first = sanitize_string(first).replace("|", "-")
    last = sanitize_string(last).replace("|", "-")
    grade = sanitize_string(grade).replace("|", "-")
    
    surname = surname_last_token(last)
    firstname = firstname_first_token(first, last)
    grade_normalized = grade_norm(grade)
    
    return f"{surname}|{firstname}|{grade_normalized}"

# ─────────────────────────────────────────────────────────────
# ENHANCED FILE VALIDATION
# ─────────────────────────────────────────────────────────────
def validate_file(file) -> Tuple[bool, str]:
    """Validate uploaded file."""
    if file is None:
        return False, "No file provided"
    
    # Check file size
    file.seek(0, 2)  # Seek to end
    size_bytes = file.tell()
    file.seek(0)  # Reset to beginning
    size_mb = size_bytes / (1024 * 1024)
    
    if size_mb > config.MAX_FILE_SIZE_MB:
        return False, f"File too large: {size_mb:.1f}MB (max: {config.MAX_FILE_SIZE_MB}MB)"
    
    # Check extension
    if not any(file.name.endswith(ext) for ext in config.ALLOWED_EXTENSIONS):
        return False, f"Invalid file type. Allowed: {', '.join(config.ALLOWED_EXTENSIONS)}"
    
    return True, "Valid"

# ─────────────────────────────────────────────────────────────
# GENERIC COLUMN HELPERS (Enhanced)
# ─────────────────────────────────────────────────────────────
def find_any(df, *need_tokens):
    """
    Return first column whose UPPER header contains ALL tokens in any of the
    provided token-tuples.
    """
    if df is None or df.empty:
        return None
        
    for cand in df.columns:
        up = str(cand).strip().upper()
        for token_tuple in need_tokens:
            if all(tok in up for tok in token_tuple):
                return cand
    return None

def find_student_grade_blob_column(df):
    """
    For Blackbaud: find the 'STUDENT ... (grade)' blob column.
    """
    if df is None or df.empty:
        return None
        
    for c in df.columns:
        up = str(c).strip().upper()
        if "STUDENT" in up and "GRADE" in up:
            return c
    
    scores = {}
    for c in df.columns:
        try:
            score = df[c].astype(str).str.contains(r"\([^)]+\)\s*$", regex=True).sum()
            scores[c] = score
        except Exception:
            scores[c] = 0
            
    if not scores:
        return None
    
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else None

# ─────────────────────────────────────────────────────────────
# ENHANCED PARSERS WITH ERROR HANDLING
# ─────────────────────────────────────────────────────────────
def parse_blackbaud(file) -> pd.DataFrame:
    """Parse Blackbaud roster with enhanced error handling."""
    try:
        # Validate file
        valid, msg = validate_file(file)
        if not valid:
            st.error(f"Blackbaud file validation failed: {msg}")
            return pd.DataFrame()
        
        # Detect header row
        probe = pd.read_excel(file, header=None, nrows=config.MAX_HEADER_SCAN_ROWS, engine="openpyxl")
        want = ["FAMILY", "ID", "PARENT", "FIRST", "LAST", "STUDENT", "GRADE"]
        best_row, best_hits = 0, -1
        
        for i in range(len(probe)):
            row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
            hits = sum(w in row for w in want)
            if hits > best_hits:
                best_row, best_hits = i, hits

        if debug_log:
            st.write("🖤 Blackbaud – detected header row index:", best_row)
            st.write(f"🖤 Blackbaud – header confidence: {best_hits}/{len(want)} tokens found")

        df = pd.read_excel(file, header=best_row, engine="openpyxl").fillna("")
        df.columns = [str(c).strip() for c in df.columns]

        # Find columns
        fam_col = find_any(df, ("FAMILY", "ID"))
        pf_col = find_any(df, ("PARENT", "FIRST"), ("PRIMARY", "PARENT", "FIRST"), ("GUARDIAN", "FIRST"))
        pl_col = find_any(df, ("PARENT", "LAST"), ("PRIMARY", "PARENT", "LAST"), ("GUARDIAN", "LAST"))
        stu_blob_col = find_student_grade_blob_column(df)

        if debug_log:
            st.write("🖤 Blackbaud – columns detected:", {
                "FAMILY ID": fam_col,
                "PARENT FIRST": pf_col,
                "PARENT LAST": pl_col,
                "STUDENT+GRADE BLOB": stu_blob_col,
            })

        if not stu_blob_col:
            st.error("Blackbaud: couldn't find the student + (grade) column. Please check your export.")
            return pd.DataFrame()

        def split_students(cell: str):
            if pd.isna(cell) or str(cell).strip() == "":
                return []
            text = re.sub(r"\s*\)\s*[,/;|]?\s*", ")|", str(cell))
            return [p.strip().rstrip(",;/|") for p in text.split("|") if p.strip()]

        def parse_student_entry(entry: str):
            m = re.search(r"\(([^)]+)\)\s*$", entry)
            grade = m.group(1).strip() if m else ""
            name = re.sub(r"\([^)]+\)\s*$", "", entry).strip()

            if ";" in name:
                last, first = [t.strip() for t in name.split(";", 1)]
            elif "," in name:
                last, first = [t.strip() for t in name.split(",", 1)]
            else:
                toks = name.split()
                if len(toks) >= 2:
                    last = " ".join(toks[:-1])
                    first = toks[-1]
                else:
                    last, first = name, ""

            return sanitize_string(last), sanitize_string(first), sanitize_string(grade)

        rows = []
        for _, r in df.iterrows():
            fam = str(r.get(fam_col, "")).replace(".0", "").strip() if fam_col else ""
            pf = sanitize_string(r.get(pf_col, "")) if pf_col else ""
            pl = sanitize_string(r.get(pl_col, "")) if pl_col else ""
            
            for entry in split_students(r.get(stu_blob_col, "")):
                l, f, g = parse_student_entry(entry)
                rows.append({
                    "ID": "",
                    "FAMILY ID": fam,
                    "PARENT FIRST NAME": pf,
                    "PARENT LAST NAME": pl,
                    "STUDENT FIRST NAME": f,
                    "STUDENT LAST NAME": l,
                    "GRADE": g,
                    "REDIKER ID": "",
                    "SOURCE": "BB",
                })

        if not pf_col or not pl_col:
            st.warning("Blackbaud: Parent First/Last columns not found. Proceeding with blanks.")

        out = pd.DataFrame(rows)
        out["UNIQUE_KEY"] = [
            make_unique_key(f, l, g) for f, l, g in zip(
                out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"]
            )
        ]

        if debug_log:
            st.write(f"🖤 Blackbaud – parsed {len(out)} student records")
            st.dataframe(out.head(10))

        return out
        
    except Exception as e:
        logger.error(f"Error parsing Blackbaud file: {str(e)}")
        st.error(f"Failed to parse Blackbaud file: {str(e)}")
        return pd.DataFrame()

def parse_rediker(file) -> pd.DataFrame:
    """Parse Rediker file with enhanced error handling."""
    try:
        # Validate file
        valid, msg = validate_file(file)
        if not valid:
            st.error(f"Rediker file validation failed: {msg}")
            return pd.DataFrame()
        
        # Detect header row
        probe = pd.read_excel(file, header=None, nrows=12, engine="openpyxl")
        tokens = {"APID", "STUDENT", "STUDENT NAME", "FIRST", "LAST", "GRADE", "UNIQUE"}
        best_row, best_hits = 0, -1
        
        for i in range(len(probe)):
            row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
            hits = sum(tok in row for tok in tokens)
            if hits > best_hits:
                best_row, best_hits = i, hits

        if debug_log:
            st.write("🔴 Rediker – detected header row index:", best_row)
            st.write(f"🔴 Rediker – header confidence: {best_hits}/{len(tokens)} tokens found")

        df = pd.read_excel(file, header=best_row, engine="openpyxl").fillna("")
        df.columns = [str(c).strip() for c in df.columns]
        U = {c.upper(): c for c in df.columns}

        # Find columns
        student_col = U.get("STUDENT NAME") or U.get("STUDENT") or U.get("STUDENT_NAME")
        if not student_col:
            st.error("Rediker: couldn't find STUDENT NAME column.")
            return pd.DataFrame()

        parent_first_col = U.get("FIRST NAME") or U.get("FIRST")
        parent_last_col = U.get("LAST NAME") or U.get("LAST")

        # Find grade column
        grade_keys = (
            "GRADE", "GRADE LEVEL", "GRADELEVEL", "GR", "GR LEVEL",
            "GRLEVEL", "CURRENT GRADE", "CUR GRADE"
        )
        grade_col = None
        for k, orig in U.items():
            kk = " ".join(k.split())
            if kk in grade_keys or ("GRADE" in kk and "FAMILY" not in kk):
                grade_col = orig
                break
                
        if not grade_col:
            st.warning("Rediker: no GRADE column found. Proceeding with blanks.")
            df["__GradeBlank"] = ""
            grade_col = "__GradeBlank"

        fam_col = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
        rid_col = U.get("APID") or U.get("UNIQUE ID") or U.get("UNIQUEID") or U.get("ID")

        if debug_log:
            st.write("🔴 Rediker – detected columns:", {
                "STUDENT NAME": student_col,
                "PARENT FIRST": parent_first_col,
                "PARENT LAST": parent_last_col,
                "GRADE": grade_col,
                "FAMILY ID": fam_col,
                "REDIKER ID": rid_col,
            })

        def split_student_name(val: str):
            if pd.isna(val) or str(val).strip() == "":
                return "", ""
            s = str(val).strip()
            if ";" in s:
                last, first = [t.strip() for t in s.split(";", 1)]
            elif "," in s:
                last, first = [t.strip() for t in s.split(",", 1)]
            else:
                parts = s.split()
                if len(parts) >= 2:
                    first = " ".join(parts[:-1])
                    last = parts[-1]
                elif len(parts) == 1:
                    first, last = parts[0], ""
                else:
                    first, last = "", ""
            return sanitize_string(first), sanitize_string(last)

        rows = []
        for _, r in df.iterrows():
            s_first, s_last = split_student_name(r.get(student_col, ""))
            p_first = sanitize_string(r.get(parent_first_col, "")) if parent_first_col else ""
            p_last = sanitize_string(r.get(parent_last_col, "")) if parent_last_col else ""
            grade = sanitize_string(r.get(grade_col, "")) if grade_col else ""
            fam = str(r.get(fam_col, "")).replace(".0", "").strip() if fam_col else ""
            rid = str(r.get(rid_col, "")).replace(".0", "").strip() if rid_col else ""

            rows.append({
                "ID": "",
                "FAMILY ID": fam,
                "PARENT FIRST NAME": p_first,
                "PARENT LAST NAME": p_last,
                "STUDENT FIRST NAME": s_first,
                "STUDENT LAST NAME": s_last,
                "GRADE": grade,
                "REDIKER ID": rid,
                "SOURCE": "RED",
            })

        out = pd.DataFrame(rows)
        out["UNIQUE_KEY"] = [
            make_unique_key(f, l, g) for f, l, g in zip(
                out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"]
            )
        ]

        if debug_log:
            st.write(f"🔴 Rediker – parsed {len(out)} student records")
            st.dataframe(out.head(10))

        return out
        
    except Exception as e:
        logger.error(f"Error parsing Rediker file: {str(e)}")
        st.error(f"Failed to parse Rediker file: {str(e)}")
        return pd.DataFrame()

def parse_student_records(file) -> pd.DataFrame:
    """Parse Student Records with enhanced error handling."""
    try:
        # Validate file
        valid, msg = validate_file(file)
        if not valid:
            st.error(f"Student Records file validation failed: {msg}")
            return pd.DataFrame()
            
        df = pd.read_excel(file, engine="openpyxl").fillna("")
        df.columns = [str(c).strip() for c in df.columns]
        U = {c.upper(): c for c in df.columns}

        if debug_log:
            st.write("💚 Student Records – columns:", list(df.columns))

        # Find columns
        col_id = list(df.columns)[0] if len(df.columns) else None
        col_fam = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
        col_red = U.get("REDIKER ID") or U.get("REDIKERID") or U.get("REDIKER_ID")
        col_pf = U.get("PARENT FIRST NAME") or U.get("PARENT FIRST")
        col_pl = U.get("PARENT LAST NAME") or U.get("PARENT LAST")

        # Student name columns
        col_sf = U.get("STUDENT FIRST NAME") or U.get("CHILD FIRST NAME") or U.get("FIRST NAME") or U.get("FIRST")
        col_sl = U.get("STUDENT LAST NAME") or U.get("CHILD LAST NAME") or U.get("LAST NAME") or U.get("LAST")

        # Handle combined name columns
        if (not col_sf or not col_sl) and (U.get("STUDENT NAME") or U.get("CHILD NAME") or U.get("NAME")):
            name_col = U.get("STUDENT NAME") or U.get("CHILD NAME") or U.get("NAME")
            series = df[name_col].astype(str).str.strip()
            split = series.str.split(",", n=1, expand=True)
            if split.shape[1] != 2:
                split = series.str.split(";", n=1, expand=True)
            if split.shape[1] == 2:
                df["__Last"], df["__First"] = split[0].str.strip(), split[1].str.strip()
                col_sf, col_sl = "__First", "__Last"

        if not col_sf or not col_sl:
            st.error("Student Records: couldn't find student FIRST/LAST name columns.")
            return pd.DataFrame()

        col_grade = U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR")
        if not col_grade:
            st.warning("Student Records: no GRADE column found. Proceeding with blanks.")
            df["__GradeBlank"] = ""
            col_grade = "__GradeBlank"

        if debug_log:
            st.write("💚 Student Records – detected columns:", {
                "ID": col_id,
                "FAMILY ID": col_fam,
                "PARENT FIRST": col_pf,
                "PARENT LAST": col_pl,
                "STUDENT FIRST": col_sf,
                "STUDENT LAST": col_sl,
                "GRADE": col_grade,
                "REDIKER ID": col_red,
            })

        out = pd.DataFrame({
            "ID": df[col_id].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_id else "",
            "FAMILY ID": df[col_fam].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_fam else "",
            "PARENT FIRST NAME": df[col_pf].apply(sanitize_string) if col_pf else "",
            "PARENT LAST NAME": df[col_pl].apply(sanitize_string) if col_pl else "",
            "STUDENT FIRST NAME": df[col_sf].apply(sanitize_string),
            "STUDENT LAST NAME": df[col_sl].apply(sanitize_string),
            "GRADE": df[col_grade].apply(sanitize_string),
            "REDIKER ID": df[col_red].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_red else "",
            "SOURCE": "SR",
        })

        # Remove rows with no student name
        before = len(out)
        out = out[~((out["STUDENT FIRST NAME"] == "") & (out["STUDENT LAST NAME"] == ""))].copy()
        dropped = before - len(out)
        if dropped > 0:
            st.warning(f"Student Records: dropped {dropped} row(s) with no usable student name.")

        out["UNIQUE_KEY"] = [
            make_unique_key(f, l, g) for f, l, g in zip(
                out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"]
            )
        ]

        if debug_log:
            st.write(f"💚 Student Records – parsed {len(out)} student records")
            st.dataframe(out.head(10))

        return out
        
    except Exception as e:
        logger.error(f"Error parsing Student Records file: {str(e)}")
        st.error(f"Failed to parse Student Records file: {str(e)}")
        return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
# UI – FILE UPLOADS
# ─────────────────────────────────────────────────────────────
st.subheader("1. Upload source rosters")

c1, c2, c3 = st.columns(3)
with c1:
    f_bb = st.file_uploader("Blackbaud Roster", type=config.ALLOWED_EXTENSIONS, key="bb")
with c2:
    f_red = st.file_uploader("Rediker", type=config.ALLOWED_EXTENSIONS, key="red")
with c3:
    f_sr = st.file_uploader("Student Records", type=config.ALLOWED_EXTENSIONS, key="sr")

if not (f_bb and f_red and f_sr):
    st.info("Upload all three files to proceed.")
    st.stop()

run = st.button("2. Build Master_Students Excel", type="primary")

# ─────────────────────────────────────────────────────────────
# MAIN PROCESS
# ─────────────────────────────────────────────────────────────
if run:
    with st.spinner("Parsing, matching, and building Excel..."):
        try:
            # Parse all files
            bb_df = parse_blackbaud(f_bb)
            red_df = parse_rediker(f_red)
            sr_df = parse_student_records(f_sr)
            
            # Check if any parsing failed
            if bb_df.empty or red_df.empty or sr_df.empty:
                st.error("Failed to parse one or more files. Please check the files and try again.")
                st.stop()

            TARGET = [
                "ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
                "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
                "REDIKER ID", "SOURCE", "UNIQUE_KEY"
            ]

            combined = pd.concat(
                [bb_df[TARGET], red_df[TARGET], sr_df[TARGET]],
                ignore_index=True
            )

            # Statistics
            if show_stats:
                st.subheader("📊 Processing Statistics")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Blackbaud Records", len(bb_df))
                with col2:
                    st.metric("Rediker Records", len(red_df))
                with col3:
                    st.metric("Student Records", len(sr_df))
                with col4:
                    st.metric("Total Records", len(combined))

            # Presence count per UNIQUE_KEY
            src_counts = combined.groupby("UNIQUE_KEY")["SOURCE"].nunique().to_dict()
            combined["__SRC_PRESENT"] = combined["UNIQUE_KEY"].map(src_counts).fillna(0).astype(int)

            # Sort
            order = {"BB": 0, "RED": 1, "SR": 2}
            combined["_source_rank"] = combined["SOURCE"].map(lambda x: order.get(str(x).upper(), 99))

            master = combined.sort_values(
                by=["UNIQUE_KEY", "_source_rank", "STUDENT LAST NAME", "STUDENT FIRST NAME"],
                kind="mergesort"
            ).reset_index(drop=True)

            # Create summaries
            summary_rows = []
            for key, grp in master.groupby("UNIQUE_KEY"):
                parts = key.split("|")
                surname = parts[0] if len(parts) >= 1 else ""
                first = parts[1] if len(parts) >= 2 else ""
                grade = parts[2] if len(parts) >= 3 else ""

                in_bb = any(grp["SOURCE"].str.upper() == "BB")
                in_red = any(grp["SOURCE"].str.upper() == "RED")
                in_sr = any(grp["SOURCE"].str.upper() == "SR")
                present_count = int(in_bb) + int(in_red) + int(in_sr)

                raw_bb = [
                    f"{r['STUDENT LAST NAME']} {r['STUDENT FIRST NAME']}"
                    for _, r in grp.iterrows() if str(r["SOURCE"]).upper() == "BB"
                ]
                raw_red = [
                    f"{r['STUDENT LAST NAME']} {r['STUDENT FIRST NAME']}"
                    for _, r in grp.iterrows() if str(r["SOURCE"]).upper() == "RED"
                ]
                raw_sr = [
                    f"{r['STUDENT LAST NAME']} {r['STUDENT FIRST NAME']}"
                    for _, r in grp.iterrows() if str(r["SOURCE"]).upper() == "SR"
                ]

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

            summary = pd.DataFrame(summary_rows).sort_values(
                ["SURNAME", "GRADE", "FIRST"]
            ).reset_index(drop=True)

            # Mismatches summary
            mismatches = summary[summary["SOURCES_PRESENT"] < 3].reset_index(drop=True)

            # More statistics
            if show_stats:
                unique_students = len(summary)
                fully_matched = len(summary[summary["SOURCES_PRESENT"] == 3])
                partial_matched = len(summary[summary["SOURCES_PRESENT"] == 2])
                single_source = len(summary[summary["SOURCES_PRESENT"] == 1])
                
                st.subheader("📊 Match Statistics")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Unique Students", unique_students)
                with col2:
                    st.metric("Full Matches (3 sources)", fully_matched, 
                             f"{fully_matched/unique_students*100:.1f}%")
                with col3:
                    st.metric("Partial Matches (2 sources)", partial_matched,
                             f"{partial_matched/unique_students*100:.1f}%")
                with col4:
                    st.metric("Single Source Only", single_source,
                             f"{single_source/unique_students*100:.1f}%")

            # Prepare output
            master_out = master[
                [
                    "ID",
                    "FAMILY ID",
                    "PARENT FIRST NAME",
                    "PARENT LAST NAME",
                    "STUDENT FIRST NAME",
                    "STUDENT LAST NAME",
                    "GRADE",
                    "REDIKER ID",
                    "SOURCE",
                    "UNIQUE_KEY",
                    "__SRC_PRESENT",
                ]
            ].copy()

            # ─────────────────────────────────────────────────────
            # WRITE EXCEL
            # ─────────────────────────────────────────────────────
            import xlsxwriter

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                # Master sheet
                master_out.to_excel(writer, index=False, sheet_name="Master")
                wb = writer.book
                ws1 = writer.sheets["Master"]

                # Create formats
                header_fmt = wb.add_format({"bold": True})
                fmt_bb = wb.add_format({"font_color": config.COLORS['blackbaud']})
                fmt_red = wb.add_format({"font_color": config.COLORS['rediker']})
                fmt_sr = wb.add_format({"font_color": config.COLORS['student_records']})

                fmt_bb_warn = wb.add_format({
                    "font_color": config.COLORS['blackbaud'], 
                    "bg_color": config.COLORS['warning'], 
                    "bold": True
                })
                fmt_red_warn = wb.add_format({
                    "font_color": config.COLORS['rediker'], 
                    "bg_color": config.COLORS['warning'], 
                    "bold": True
                })
                fmt_sr_warn = wb.add_format({
                    "font_color": config.COLORS['student_records'], 
                    "bg_color": config.COLORS['warning'], 
                    "bold": True
                })

                fmt_bb_severe = wb.add_format({
                    "font_color": config.COLORS['blackbaud'], 
                    "bg_color": config.COLORS['severe'], 
                    "bold": True
                })
                fmt_red_severe = wb.add_format({
                    "font_color": config.COLORS['rediker'], 
                    "bg_color": config.COLORS['severe'], 
                    "bold": True
                })
                fmt_sr_severe = wb.add_format({
                    "font_color": config.COLORS['student_records'], 
                    "bg_color": config.COLORS['severe'], 
                    "bold": True
                })

                # Header row
                for c_idx, col in enumerate(master_out.columns):
                    ws1.write(0, c_idx, col, header_fmt)

                # Autosize columns
                for i, col in enumerate(master_out.columns):
                    vals = master_out[col].astype(str).head(2000).tolist()
                    width = min(
                        max([len(str(col))] + [len(v) for v in vals]) + 2, 
                        config.EXCEL_MAX_COL_WIDTH
                    )
                    width = max(width, config.EXCEL_MIN_COL_WIDTH)
                    ws1.set_column(i, i, width)

                # Write data with formatting
                idx = {c: i for i, c in enumerate(master_out.columns)}
                s_col = idx["SOURCE"]
                present_col = idx["__SRC_PRESENT"]
                n_rows, n_cols = master_out.shape

                for r in range(n_rows):
                    src = str(master_out.iat[r, s_col]).strip().upper()
                    present_count = int(master_out.iat[r, present_col])

                    # Choose format
                    if src == "RED":
                        base_fmt, warn_fmt, severe_fmt = fmt_red, fmt_red_warn, fmt_red_severe
                    elif src == "SR":
                        base_fmt, warn_fmt, severe_fmt = fmt_sr, fmt_sr_warn, fmt_sr_severe
                    else:
                        base_fmt, warn_fmt, severe_fmt = fmt_bb, fmt_bb_warn, fmt_bb_severe

                    if present_count >= 3:
                        row_fmt = base_fmt
                    elif present_count == 2:
                        row_fmt = warn_fmt
                    else:
                        row_fmt = severe_fmt

                    for c in range(n_cols):
                        ws1.write(r + 1, c, master_out.iat[r, c], row_fmt)

                # Summary sheet
                summary.to_excel(writer, index=False, sheet_name="Summary")
                ws2 = writer.sheets["Summary"]
                
                ok_fmt = wb.add_format({
                    "bg_color": config.COLORS['ok'], 
                    "font_color": config.COLORS['ok_text']
                })
                bad_fmt = wb.add_format({
                    "bg_color": config.COLORS['bad'], 
                    "font_color": config.COLORS['bad_text']
                })

                for c_idx, col in enumerate(summary.columns):
                    ws2.write(0, c_idx, col, header_fmt)

                for i, col in enumerate(summary.columns):
                    vals = summary[col].astype(str).head(2000).tolist()
                    width = min(
                        max([len(str(col))] + [len(v) for v in vals]) + 2, 
                        config.EXCEL_MAX_COL_WIDTH
                    )
                    width = max(width, config.EXCEL_MIN_COL_WIDTH)
                    ws2.set_column(i, i, width)

                col_idx = {c: i for i, c in enumerate(summary.columns)}
                for r in range(len(summary)):
                    for src_col in ["BB", "RED", "SR"]:
                        val = summary.iat[r, col_idx[src_col]]
                        ws2.write(r + 1, col_idx[src_col], val, ok_fmt if val == "✅" else bad_fmt)

                # Summary_Mismatches sheet
                mismatches.to_excel(writer, index=False, sheet_name="Summary_Mismatches")
                ws3 = writer.sheets["Summary_Mismatches"]

                for c_idx, col in enumerate(mismatches.columns):
                    ws3.write(0, c_idx, col, header_fmt)

                for i, col in enumerate(mismatches.columns):
                    vals = mismatches[col].astype(str).head(2000).tolist()
                    width = min(
                        max([len(str(col))] + [len(v) for v in vals]) + 2, 
                        config.EXCEL_MAX_COL_WIDTH
                    )
                    width = max(width, config.EXCEL_MIN_COL_WIDTH)
                    ws3.set_column(i, i, width)

                mis_col_idx = {c: i for i, c in enumerate(mismatches.columns)}
                for r in range(len(mismatches)):
                    for src_col in ["BB", "RED", "SR"]:
                        val = mismatches.iat[r, mis_col_idx[src_col]]
                        ws3.write(r + 1, mis_col_idx[src_col], val, ok_fmt if val == "✅" else bad_fmt)

            # Generate filename
            eastern = pytz.timezone("America/New_York")
            ts = datetime.now(eastern).strftime("%y%m%d_%H%M")
            file_name = f"{ts}_Master_Students.xlsx"

            st.success("✅ Master_Students workbook generated successfully!")
            st.download_button(
                label=f"⬇️ Download {file_name}",
                data=output.getvalue(),
                file_name=file_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            
        except Exception as e:
            logger.error(f"Critical error in main process: {str(e)}")
            st.error(f"An error occurred while processing: {str(e)}")
            st.error("Please check your files and try again. If the problem persists, contact support.")

# ─────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────
build_id = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
st.markdown(
    f"<hr><div style='text-align:center; font-size:0.8em; color:#888;'>"
    f"Build ID: <b>{build_id}</b> • Dataset Reconciliation v{config.VERSION}"
    f"</div>",
    unsafe_allow_html=True,
)
