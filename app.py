# app.py – Dataset Comparison
# Version 1.0.1 – 2025-11-19 18:00 ET

import io
import re
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Dataset Comparison", page_icon="📘", layout="centered")

st.title("📘 Dataset Comparison")
st.caption("Upload Blackbaud, Rediker, and Student Records → get a styled Excel with Master + Summary tabs.")

# ──────────────────────────────────────────────────────────────────────────────
# NORMALIZATION HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def norm_piece(s: str) -> str:
    """
    Uppercase, keep letters/digits/spaces/hyphens, strip.
    """
    return re.sub(r"[^A-Z0-9 \-]+", "", str(s).upper()).strip()


def grade_norm(s: str) -> str:
    """
    Normalize grade strings so that:
      - P4, P 4, PK4, PK 4, PREK4, PRE-K4, etc.       →  PK4
      - P3, PK3, PREK3, PRE-K3, etc.                  →  PK3
      - 0K, OK, K, KG, KDG, KINDER, KINDERGARTEN, etc.→  K
      - 04, 4, G4, GR4, GRADE4, 4TH, etc.             →  4
    """
    if s is None:
        return ""

    x = norm_piece(s)
    x = re.sub(r"\s+", "", x)
    if x == "":
        return ""

    # Pre-K 4
    if (re.fullmatch(r"P[K]?4", x) or x in {"PREK4", "PREK", "PRE-K4", "PRE-K"}):
        return "PK4"

    # Pre-K 3
    if (re.fullmatch(r"P[K]?3", x) or x in {"PREK3", "PRE-K3"}):
        return "PK3"

    # Kindergarten
    if (
        x in {"K", "KG", "KDG", "KINDER", "KINDERGARTEN"}
        or re.fullmatch(r"0K", x)
        or re.fullmatch(r"OK", x)
        or re.fullmatch(r"K0", x)
        or re.fullmatch(r"K-?0", x)
        or re.fullmatch(r"KINDERGARTEN", x)
    ):
        return "K"

    # Grades 1–12
    m = re.fullmatch(r"(?:GRADE|GR|G)?0*([1-9]|1[0-2])", x)
    if m:
        return m.group(1)

    m = re.search(r"0*([1-9]|1[0-2])(ST|ND|RD|TH)?", x)
    if m:
        return m.group(1)

    return x


def surname_last_token(last: str) -> str:
    """
    Use the last *true* surname token.
    Handles suffixes like JR, SR, II, III, IV, V by ignoring them.
    """
    s = norm_piece(last).replace("-", " ")
    toks = [t for t in s.split() if t]
    if not toks:
        return ""
    suffixes = {"JR", "SR", "II", "III", "IV", "V"}
    if toks[-1] in suffixes and len(toks) >= 2:
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


def make_unique_key_lenient(first: str, last: str, grade: str) -> str:
    """
    Student identity key used across datasets:
      SURNAME_TOKEN(LAST) | FIRST_TOKEN | NORMALIZED_GRADE
    """
    return f"{surname_last_token(last)}|{firstname_first_token(first, last)}|{grade_norm(grade)}"

# ──────────────────────────────────────────────────────────────────────────────
# GENERIC COLUMN-FINDING UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def find_any(df, *need_tokens):
    """
    Return first column whose UPPER header contains ALL tokens in any of the
    provided token-tuples. Example:
      find_any(df, ("PARENT","FIRST"), ("PARENT 1","FIRST"), ("GUARDIAN","FIRST"))
    """
    for cand in df.columns:
        up = str(cand).strip().upper()
        for token_tuple in need_tokens:
            if all(tok in up for tok in token_tuple):
                return cand
    return None


def find_student_grade_blob_column(df):
    """
    For Blackbaud: find the 'STUDENT ... (grade)' blob column.
    Prefer headers containing STUDENT and GRADE, else a column with many '(...)' endings.
    """
    for c in df.columns:
        up = str(c).strip().upper()
        if "STUDENT" in up and "GRADE" in up:
            return c
    scores = {c: df[c].astype(str).str.contains(r"\([^)]+\)\s*$", regex=True).sum() for c in df.columns}
    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else None

# ──────────────────────────────────────────────────────────────────────────────
# BLACKBAUD PARSER
# ──────────────────────────────────────────────────────────────────────────────
def parse_blackbaud(file) -> pd.DataFrame:
    # Detect header row in first 25 lines
    probe = pd.read_excel(file, header=None, nrows=25, engine="openpyxl")
    want = ["FAMILY", "ID", "PARENT", "FIRST", "LAST", "STUDENT", "GRADE"]
    best_row, best_hits = 0, -1
    for i in range(len(probe)):
        row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
        hits = sum(w in row for w in want)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row, engine="openpyxl").fillna("")
    df.columns = [str(c).strip() for c in df.columns]

    # Flexible column finding
    fam_col = find_any(df, ("FAMILY", "ID"))
    pf_col = find_any(
        df, ("PARENT", "FIRST"),
        ("PARENT 1", "FIRST"), ("P1", "FIRST"),
        ("PRIMARY", "PARENT", "FIRST"),
        ("GUARDIAN", "FIRST"),
        ("CONTACT 1", "FIRST"), ("CONTACT1", "FIRST")
    )
    pl_col = find_any(
        df, ("PARENT", "LAST"),
        ("PARENT 1", "LAST"), ("P1", "LAST"),
        ("PRIMARY", "PARENT", "LAST"),
        ("GUARDIAN", "LAST"),
        ("CONTACT 1", "LAST"), ("CONTACT1", "LAST")
    )
    stu_blob_col = find_student_grade_blob_column(df)

    if not stu_blob_col:
        st.error("Blackbaud: couldn’t find the student + (grade) column. Please check your export.")
        st.stop()

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
            if len(toks) >= 3:
                last, first = toks[0], " ".join(toks[1:])
            elif len(toks) == 2:
                last, first = toks[0], toks[1]
            else:
                last, first = name, ""
        return last, first, grade

    rows = []
    for _, r in df.iterrows():
        fam = str(r.get(fam_col, "")).replace(".0", "").strip() if fam_col else ""
        pf = str(r.get(pf_col, "")).strip() if pf_col else ""
        pl = str(r.get(pl_col, "")).strip() if pl_col else ""
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
                "UNIQUE_KEY": make_unique_key_lenient(f, l, g),
            })

    if not pf_col or not pl_col:
        st.warning("Blackbaud: Parent First/Last columns not found. Proceeding with blanks for those fields.")

    return pd.DataFrame(rows)

# ──────────────────────────────────────────────────────────────────────────────
# REDIKER PARSER (STUDENT NAME for student, FIRST/LAST for parent)
# ──────────────────────────────────────────────────────────────────────────────
def parse_rediker(file) -> pd.DataFrame:
    """
    Rediker export where:
      - STUDENT NAME = student full name
      - FIRST NAME / LAST NAME = parent names
      - APID (or UNIQUE ID) = student ID
    """
    # Detect header row in first ~12 lines
    probe = pd.read_excel(file, header=None, nrows=12, engine="openpyxl")
    tokens = {"APID", "STUDENT", "STUDENT NAME", "FIRST", "LAST", "GRADE", "UNIQUE"}
    best_row, best_hits = 0, -1
    for i in range(len(probe)):
        row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
        hits = sum(tok in row for tok in tokens)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row, engine="openpyxl").fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    U = {c.upper(): c for c in df.columns}

    # STUDENT name column
    student_col = (
        U.get("STUDENT NAME")
        or U.get("STUDENT")
        or U.get("STUDENT_NAME")
    )
    if not student_col:
        st.error("Rediker: couldn’t find STUDENT NAME column. Please check the export.")
        st.stop()

    # Parent name columns
    parent_first_col = U.get("FIRST NAME") or U.get("FIRST")
    parent_last_col = U.get("LAST NAME") or U.get("LAST")

    # Grade column (detected, normalization handled later by grade_norm)
    grade_keys = (
        "GRADE", "GRADE LEVEL", "GRADELEVEL", "GR", "GR LEVEL",
        "GRLEVEL", "GRADE_LVL", "CURRENT GRADE", "CUR GRADE", "LVL"
    )
    grade_col = None
    for k, orig in U.items():
        kk = " ".join(k.split())
        if kk in grade_keys or ("GRADE" in kk and "FAMILY" not in kk):
            grade_col = orig
            break

    if not grade_col:
        st.warning("Rediker: no GRADE column found. Proceeding with blanks.")

    # Family ID and Rediker ID
    fam_col = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    rid_col = U.get("APID") or U.get("UNIQUE ID") or U.get("UNIQUEID") or U.get("ID")

    def split_student_name(val: str):
        if pd.isna(val) or str(val).strip() == "":
            return "", ""
        s = str(val).strip()
        # Common patterns: "RIVERA; AIDEN", "RIVERA, AIDEN", "AIDEN RIVERA"
        if ";" in s:
            last, first = [t.strip() for t in s.split(";", 1)]
        elif "," in s:
            last, first = [t.strip() for t in s.split(",", 1)]
        else:
            parts = s.split()
            if len(parts) >= 2:
                # Assume "FIRST LAST" if just space-separated
                first = " ".join(parts[:-1])
                last = parts[-1]
            elif len(parts) == 1:
                first, last = parts[0], ""
            else:
                first, last = "", ""
        return first, last

    rows = []
    for _, r in df.iterrows():
        stud_first, stud_last = split_student_name(r.get(student_col, ""))

        parent_first = str(r.get(parent_first_col, "")).strip() if parent_first_col else ""
        parent_last = str(r.get(parent_last_col, "")).strip() if parent_last_col else ""

        if grade_col:
            grade = str(r.get(grade_col, "")).strip()
        else:
            grade = ""

        fam = str(r.get(fam_col, "")).replace(".0", "").strip() if fam_col else ""
        rid = str(r.get(rid_col, "")).replace(".0", "").strip() if rid_col else ""

        rows.append({
            "ID": "",
            "FAMILY ID": fam,
            "PARENT FIRST NAME": parent_first,
            "PARENT LAST NAME": parent_last,
            "STUDENT FIRST NAME": stud_first,
            "STUDENT LAST NAME": stud_last,
            "GRADE": grade,
            "REDIKER ID": rid,
            "SOURCE": "RED",
            "UNIQUE_KEY": make_unique_key_lenient(stud_first, stud_last, grade),
        })

    return pd.DataFrame(rows)

# ──────────────────────────────────────────────────────────────────────────────
# STUDENT RECORDS PARSER (tolerant)
# ──────────────────────────────────────────────────────────────────────────────
def parse_student_records(file) -> pd.DataFrame:
    # Detect a plausible header row
    probe = pd.read_excel(file, header=None, nrows=20, engine="openpyxl")
    clues = ["STUDENT", "FIRST", "LAST", "NAME", "GRADE", "FAMILY", "REDIKER", "ID"]
    best_row, best_hits = 0, -1
    for i in range(len(probe)):
        row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
        hits = sum(cl in row for cl in clues)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row, engine="openpyxl").fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    U = {c.upper(): c for c in df.columns}

    # Try many variants
    col_id = list(df.columns)[0] if len(df.columns) else None
    col_fam = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    col_red = U.get("REDIKER ID") or U.get("REDIKERID") or U.get("REDIKER_ID")
    col_sf = U.get("STUDENT FIRST NAME") or U.get("FIRST NAME") or U.get("FIRST") or U.get("LEGAL FIRST") or U.get("PREFERRED FIRST")
    col_sl = U.get("STUDENT LAST NAME") or U.get("LAST NAME") or U.get("LAST") or U.get("LEGAL LAST")
    name_col = U.get("STUDENT NAME") or U.get("NAME") or U.get("FULL NAME") or U.get("CHILD NAME") or U.get("STUDENT")
    col_grade = U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR") or U.get("CURRENT GRADE")

    # If FIRST/LAST missing but NAME exists, split it
    def split_name_cell(val: str):
        if pd.isna(val) or str(val).strip() == "":
            return "", ""
        s = str(val).strip()
        if ";" in s:
            last, first = [t.strip() for t in s.split(";", 1)]
        elif "," in s:
            last, first = [t.strip() for t in s.split(",", 1)]
        else:
            toks = s.split()
            # Prefer "FIRST LAST" for SR
            if len(toks) >= 2:
                first = " ".join(toks[:-1])
                last = toks[-1]
            elif len(toks) == 1:
                first, last = toks[0], ""
            else:
                first, last = "", ""
        return first, last

    if (not col_sf or not col_sl) and name_col:
        split = df[name_col].apply(split_name_cell).tolist()
        df["__First"], df["__Last"] = zip(*split) if split else ([], [])
        col_sf, col_sl = "__First", "__Last"

    # Last resort: guess a NAME-like column by content
    if not (col_sf and col_sl):
        namey = None
        best_score = -1
        for c in df.columns:
            series = df[c].astype(str)
            score = ((series.str.contains(r"[A-Za-z]") & series.str.contains(r"\s")).mean())
            if score > best_score:
                best_score, namey = score, c
        if namey and best_score >= 0.3:
            split = df[namey].apply(split_name_cell).tolist()
            df["__First2"], df["__Last2"] = zip(*split) if split else ([], [])
            col_sf, col_sl = "__First2", "__Last2"

    # If STILL missing both names, proceed with blanks but warn
    if not (col_sf and col_sl):
        st.warning("Student Records: could not find FIRST/LAST or a usable NAME column. Proceeding with blanks; such rows may be dropped.")
        df["__FirstBlank"] = ""
        df["__LastBlank"] = ""
        col_sf, col_sl = "__FirstBlank", "__LastBlank"

    # If grade missing, keep blanks but warn
    if not col_grade:
        st.warning("Student Records: no GRADE column found. Proceeding with blanks.")
        df["__GradeBlank"] = ""
        col_grade = "__GradeBlank"

    out = pd.DataFrame({
        "ID": df[col_id].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_id else "",
        "FAMILY ID": df[col_fam].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_fam else "",
        "PARENT FIRST NAME": df[U.get("PARENT FIRST NAME")].astype(str).str.strip() if U.get("PARENT FIRST NAME") else "",
        "PARENT LAST NAME": df[U.get("PARENT LAST NAME")].astype(str).str.strip() if U.get("PARENT LAST NAME") else "",
        "STUDENT FIRST NAME": df[col_sf].astype(str).str.strip(),
        "STUDENT LAST NAME": df[col_sl].astype(str).str.strip(),
        "GRADE": df[col_grade].astype(str).str.strip(),
        "REDIKER ID": df[col_red].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_red else "",
        "SOURCE": "SR",
    })

    before = len(out)
    out = out[~((out["STUDENT FIRST NAME"] == "") & (out["STUDENT LAST NAME"] == ""))].copy()
    dropped = before - len(out)
    if dropped > 0:
        st.warning(f"Student Records: dropped {dropped} row(s) with no usable student name.")

    out["UNIQUE_KEY"] = [
        make_unique_key_lenient(f, l, g)
        for f, l, g in zip(out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"])
    ]
    return out

# ──────────────────────────────────────────────────────────────────────────────
# UI — UPLOADS
# ──────────────────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    f_bb = st.file_uploader("Blackbaud", type=["xlsx", "xls"])
with col2:
    f_red = st.file_uploader("Rediker", type=["xlsx", "xls"])
with col3:
    f_sr = st.file_uploader("Student Records", type=["xlsx", "xls"])

run = st.button("Build Excel Comparison", type="primary", disabled=not (f_bb and f_red and f_sr))

# ──────────────────────────────────────────────────────────────────────────────
# MAIN PROCESS
# ──────────────────────────────────────────────────────────────────────────────
if run:
    with st.spinner("Parsing & normalizing..."):
        bb_df = parse_blackbaud(f_bb)
        red_df = parse_rediker(f_red)
        sr_df = parse_student_records(f_sr)

    TARGET = [
        "ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
        "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE", "REDIKER ID",
        "SOURCE", "UNIQUE_KEY"
    ]
    master = pd.concat([bb_df[TARGET], red_df[TARGET], sr_df[TARGET]], ignore_index=True)

    # Helpers for grouping/presence
    master["__SURNAME"] = master["STUDENT LAST NAME"].apply(surname_last_token)
    master["__FIRSTTOK"] = master.apply(
        lambda r: firstname_first_token(r["STUDENT FIRST NAME"], r["STUDENT LAST NAME"]), axis=1
    )
    master["__GRADELEN"] = master["GRADE"].apply(grade_norm)

    # Student-level key: SURNAME|FIRSTTOKEN|GRADELEN
    master["__GROUP_KEY"] = master["__SURNAME"] + "|" + master["__FIRSTTOK"] + "|" + master["__GRADELEN"]
    master["UNIQUE_KEY"] = master["__GROUP_KEY"]

    src_counts = master.groupby("__GROUP_KEY")["SOURCE"].nunique().to_dict()
    master["__SRC_PRESENT"] = master["__GROUP_KEY"].map(src_counts).fillna(0).astype(int)

    # Sort by key then source
    order = {"BB": 0, "RED": 1, "SR": 2}
    master["_source_rank"] = master["SOURCE"].map(lambda x: order.get(str(x).upper(), 99))
    master_sorted = master.sort_values(
        by=["UNIQUE_KEY", "_source_rank", "STUDENT LAST NAME", "STUDENT FIRST NAME"],
        kind="mergesort"
    ).reset_index(drop=True)

    # SUMMARY (per student key)
    summary_rows = []
    for gkey, grp in master.groupby("__GROUP_KEY"):
        parts = gkey.split("|")
        surname_token, first_token, grade = (parts + ["", ""])[:3]
        in_bb = any(grp["SOURCE"].str.upper() == "BB")
        in_red = any(grp["SOURCE"].str.upper() == "RED")
        in_sr = any(grp["SOURCE"].str.upper() == "SR")
        summary_rows.append({
            "SURNAME_TOKEN(LAST)": surname_token,
            "FIRST_TOKEN": first_token,
            "GRADE": grade,
            "BB": "✅" if in_bb else "❌",
            "RED": "✅" if in_red else "❌",
            "SR": "✅" if in_sr else "❌",
            "SOURCES_PRESENT": int(in_bb) + int(in_red) + int(in_sr),
        })
    summary = pd.DataFrame(summary_rows).sort_values(
        ["SURNAME_TOKEN(LAST)", "GRADE", "FIRST_TOKEN"]
    ).reset_index(drop=True)

    # WRITE EXCEL
    import xlsxwriter

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # Sheet 1: Master
        master_sorted.to_excel(writer, index=False, sheet_name="Master")
        wb = writer.book
        ws1 = writer.sheets["Master"]
        header_fmt = wb.add_format({"bold": True})
        fmt_bb = wb.add_format({"font_color": "#000000"})
        fmt_red = wb.add_format({"font_color": "#A10000"})
        fmt_sr = wb.add_format({"font_color": "#006400"})
        warn_fill = "#FFF59D"
        fmt_bb_warn = wb.add_format({"font_color": "#000000", "bg_color": warn_fill, "bold": True})
        fmt_red_warn = wb.add_format({"font_color": "#A10000", "bg_color": warn_fill, "bold": True})
        fmt_sr_warn = wb.add_format({"font_color": "#006400", "bg_color": warn_fill, "bold": True})

        # header
        for c_idx, col in enumerate(master_sorted.columns):
            ws1.write(0, c_idx, col, header_fmt)
        # autosize
        for i, col in enumerate(master_sorted.columns):
            vals = master_sorted[col].astype(str).head(2000).tolist()
            width = min(max([len(str(col))] + [len(v) for v in vals]) + 2, 40)
            ws1.set_column(i, i, width)

        idx = {c: i for i, c in enumerate(master_sorted.columns)}
        s_col = idx["SOURCE"]
        present_col = idx["__SRC_PRESENT"]
        n_rows, n_cols = master_sorted.shape
        for r in range(n_rows):
            src = str(master_sorted.iat[r, s_col]).strip().upper()
            present_all = int(master_sorted.iat[r, present_col]) >= 3
            base_fmt, warn_fmt = (fmt_bb, fmt_bb_warn)
            if src == "RED":
                base_fmt, warn_fmt = (fmt_red, fmt_red_warn)
            elif src == "SR":
                base_fmt, warn_fmt = (fmt_sr, fmt_sr_warn)
            fmt = base_fmt if present_all else warn_fmt  # highlight only if NOT in all 3
            for c in range(n_cols):
                ws1.write(r + 1, c, master_sorted.iat[r, c], fmt)

        # hide helpers
        for helper in ["__SURNAME", "__FIRSTTOK", "__GRADELEN", "__GROUP_KEY", "__SRC_PRESENT", "_source_rank"]:
            if helper in idx:
                ws1.set_column(idx[helper], idx[helper], None, None, {"hidden": True})

        # Sheet 2: Summary
        summary.to_excel(writer, index=False, sheet_name="Summary")
        ws2 = writer.sheets["Summary"]
        header_fmt2 = wb.add_format({"bold": True})
        ok_fmt = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100"})
        bad_fmt = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
        for c_idx, col in enumerate(summary.columns):
            ws2.write(0, c_idx, col, header_fmt2)
        for i, col in enumerate(summary.columns):
            vals = summary[col].astype(str).head(2000).tolist()
            width = min(max([len(str(col))] + [len(v) for v in vals]) + 2, 50)
            ws2.set_column(i, i, width)
        col_idx = {c: i for i, c in enumerate(summary.columns)}
        for r in range(len(summary)):
            for src_col in ["BB", "RED", "SR"]:
                val = summary.iat[r, col_idx[src_col]]
                ws2.write(r + 1, col_idx[src_col], val, ok_fmt if val == "✅" else bad_fmt)

    # Build timestamped filename in Eastern Time
    eastern = pytz.timezone("America/New_York")
    ts = datetime.now(eastern).strftime("%y%m%d_%H%M")
    file_name = f"{ts}_Dataset_Master.xlsx"

    st.success("✅ Excel generated successfully")
    st.download_button(
        label=f"⬇️ Download {file_name}",
        data=output.getvalue(),
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
