# app.py – Dataset Comparison (Reset to Master_Students format)
# Version 3.0.0 – reset-to-good-layout

import io
import re
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

VERSION = "3.0.0"

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Dataset Comparison", page_icon="📘", layout="centered")

st.title("📘 Dataset Comparison")
st.markdown(
    f"<span style='font-size: 0.8rem; color: #888;'>Version {VERSION}</span>",
    unsafe_allow_html=True,
)
st.caption(
    "Upload Blackbaud Roster, Rediker, and Student Records → builds a Master_Students Excel "
    "with a detailed Master sheet and a Summary sheet."
)

# ─────────────────────────────────────────────────────────────
# BASIC NORMALIZATION HELPERS
# ─────────────────────────────────────────────────────────────
def norm_piece(s: str) -> str:
    """Uppercase, keep letters/digits/spaces/hyphens, strip."""
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

    # PK4
    if (re.fullmatch(r"P[K]?4", x) or x in {"PREK4", "PREK", "PRE-K4", "PRE-K"}):
        return "PK4"

    # PK3
    if (re.fullmatch(r"P[K]?3", x) or x in {"PREK3", "PRE-K3"}):
        return "PK3"

    # K
    if (
        x in {"K", "KG", "KDG", "KINDER", "KINDERGARTEN"}
        or re.fullmatch(r"0K", x)
        or re.fullmatch(r"OK", x)
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
    Use the last “real” surname token (ignoring JR, SR, II, etc).
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


def make_unique_key(first: str, last: str, grade: str) -> str:
    """
    Student identity key used across datasets:
      SURNAME_TOKEN(LAST) | FIRST_TOKEN | NORMALIZED_GRADE
    """
    return f"{surname_last_token(last)}|{firstname_first_token(first, last)}|{grade_norm(grade)}"

# ─────────────────────────────────────────────────────────────
# GENERIC COLUMN HELPERS
# ─────────────────────────────────────────────────────────────
def find_any(df, *need_tokens):
    """
    Return first column whose UPPER header contains ALL tokens in any of the
    provided token-tuples. Example:
      find_any(df, ("PARENT","FIRST"), ("GUARDIAN","FIRST"))
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
    scores = {
        c: df[c].astype(str).str.contains(r"\([^)]+\)\s*$", regex=True).sum()
        for c in df.columns
    }
    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else None

# ─────────────────────────────────────────────────────────────
# BLACKBAUD PARSER – FAMILY ROWS → STUDENT ROWS
# ─────────────────────────────────────────────────────────────
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

    fam_col = find_any(df, ("FAMILY", "ID"))
    pf_col = find_any(df, ("PARENT", "FIRST"), ("PRIMARY", "PARENT", "FIRST"), ("GUARDIAN", "FIRST"))
    pl_col = find_any(df, ("PARENT", "LAST"), ("PRIMARY", "PARENT", "LAST"), ("GUARDIAN", "LAST"))
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
            })

    if not pf_col or not pl_col:
        st.warning("Blackbaud: Parent First/Last columns not found. Proceeding with blanks for those fields.")

    out = pd.DataFrame(rows)
    out["UNIQUE_KEY"] = [
        make_unique_key(f, l, g) for f, l, g in zip(
            out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"]
        )
    ]
    return out

# ─────────────────────────────────────────────────────────────
# REDIKER PARSER – STUDENT NAME, PARENT FIRST/LAST, GRADE
# ─────────────────────────────────────────────────────────────
def parse_rediker(file) -> pd.DataFrame:
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

    student_col = U.get("STUDENT NAME") or U.get("STUDENT") or U.get("STUDENT_NAME")
    if not student_col:
        st.error("Rediker: couldn’t find STUDENT NAME column. Please check the export.")
        st.stop()

    parent_first_col = U.get("FIRST NAME") or U.get("FIRST")
    parent_last_col = U.get("LAST NAME") or U.get("LAST")

    # Grade column
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

    fam_col = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    rid_col = U.get("APID") or U.get("UNIQUE ID") or U.get("UNIQUEID") or U.get("ID")

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
        return first, last

    rows = []
    for _, r in df.iterrows():
        s_first, s_last = split_student_name(r.get(student_col, ""))
        p_first = str(r.get(parent_first_col, "")).strip() if parent_first_col else ""
        p_last = str(r.get(parent_last_col, "")).strip() if parent_last_col else ""
        grade = str(r.get(grade_col, "")).strip() if grade_col else ""
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
    return out

# ─────────────────────────────────────────────────────────────
# STUDENT RECORDS PARSER – STRAIGHTFORWARD ROWS
# ─────────────────────────────────────────────────────────────
def parse_student_records(file) -> pd.DataFrame:
    df = pd.read_excel(file, engine="openpyxl").fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    U = {c.upper(): c for c in df.columns}

    col_id = list(df.columns)[0] if len(df.columns) else None
    col_fam = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    col_red = U.get("REDIKER ID") or U.get("REDIKERID") or U.get("REDIKER_ID")
    col_pf = U.get("PARENT FIRST NAME") or U.get("PARENT FIRST")
    col_pl = U.get("PARENT LAST NAME") or U.get("PARENT LAST")
    col_sf = U.get("STUDENT FIRST NAME") or U.get("FIRST NAME") or U.get("FIRST")
    col_sl = U.get("STUDENT LAST NAME") or U.get("LAST NAME") or U.get("LAST")
    col_grade = U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR")

    if not col_sf or not col_sl:
        st.error("Student Records: couldn’t find student FIRST/LAST name columns. Please adjust the export.")
        st.stop()

    if not col_grade:
        st.warning("Student Records: no GRADE column found. Proceeding with blanks.")
        df["__GradeBlank"] = ""
        col_grade = "__GradeBlank"

    out = pd.DataFrame({
        "ID": df[col_id].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_id else "",
        "FAMILY ID": df[col_fam].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_fam else "",
        "PARENT FIRST NAME": df[col_pf].astype(str).str.strip() if col_pf else "",
        "PARENT LAST NAME": df[col_pl].astype(str).str.strip() if col_pl else "",
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
        make_unique_key(f, l, g) for f, l, g in zip(
            out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"]
        )
    ]
    return out

# ─────────────────────────────────────────────────────────────
# UI – FILE UPLOADS
# ─────────────────────────────────────────────────────────────
st.subheader("1. Upload source rosters")

c1, c2, c3 = st.columns(3)
with c1:
    f_bb = st.file_uploader("Blackbaud Roster", type=["xlsx", "xls"], key="bb")
with c2:
    f_red = st.file_uploader("Rediker", type=["xlsx", "xls"], key="red")
with c3:
    f_sr = st.file_uploader("Student Records", type=["xlsx", "xls"], key="sr")

if not (f_bb and f_red and f_sr):
    st.info("Upload all three files to proceed.")
    st.stop()

run = st.button("2. Build Master_Students Excel", type="primary")

# ─────────────────────────────────────────────────────────────
# MAIN PROCESS
# ─────────────────────────────────────────────────────────────
if run:
    with st.spinner("Parsing, matching, and building Excel..."):
        bb_df = parse_blackbaud(f_bb)
        red_df = parse_rediker(f_red)
        sr_df = parse_student_records(f_sr)

        TARGET = [
            "ID", "FAMILY ID", "PARENT FIRST NAME", "PARENT LAST NAME",
            "STUDENT FIRST NAME", "STUDENT LAST NAME", "GRADE",
            "REDIKER ID", "SOURCE", "UNIQUE_KEY"
        ]

        combined = pd.concat(
            [bb_df[TARGET], red_df[TARGET], sr_df[TARGET]],
            ignore_index=True
        )

        # Presence count per UNIQUE_KEY
        src_counts = combined.groupby("UNIQUE_KEY")["SOURCE"].nunique().to_dict()
        combined["__SRC_PRESENT"] = combined["UNIQUE_KEY"].map(src_counts).fillna(0).astype(int)

        # Sort: by UNIQUE_KEY then source priority then name
        order = {"BB": 0, "RED": 1, "SR": 2}
        combined["_source_rank"] = combined["SOURCE"].map(lambda x: order.get(str(x).upper(), 99))

        master = combined.sort_values(
            by=["UNIQUE_KEY", "_source_rank", "STUDENT LAST NAME", "STUDENT FIRST NAME"],
            kind="mergesort"
        ).reset_index(drop=True)

        # Summary per UNIQUE_KEY
        summary_rows = []
        for key, grp in master.groupby("UNIQUE_KEY"):
            parts = key.split("|")
            surname_token = parts[0] if len(parts) >= 1 else ""
            first_token = parts[1] if len(parts) >= 2 else ""
            grade_token = parts[2] if len(parts) >= 3 else ""
            in_bb = any(grp["SOURCE"].str.upper() == "BB")
            in_red = any(grp["SOURCE"].str.upper() == "RED")
            in_sr = any(grp["SOURCE"].str.upper() == "SR")
            summary_rows.append({
                "UNIQUE_KEY": key,
                "SURNAME_TOKEN(LAST)": surname_token,
                "FIRST_TOKEN": first_token,
                "GRADE_NORM": grade_norm(grade_token),
                "BB": "✅" if in_bb else "❌",
                "RED": "✅" if in_red else "❌",
                "SR": "✅" if in_sr else "❌",
                "SOURCES_PRESENT": int(in_bb) + int(in_red) + int(in_sr),
            })

        summary = pd.DataFrame(summary_rows).sort_values(
            ["SURNAME_TOKEN(LAST)", "GRADE_NORM", "FIRST_TOKEN"]
        ).reset_index(drop=True)

        # We ONLY write the “visible” columns to Excel for Master
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
        # WRITE EXCEL (Master + Summary) with formatting
        # ─────────────────────────────────────────────────────
        import xlsxwriter

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            # Master sheet
            master_out.to_excel(writer, index=False, sheet_name="Master")
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

            # Header row
            for c_idx, col in enumerate(master_out.columns):
                ws1.write(0, c_idx, col, header_fmt)

            # Autosize columns
            for i, col in enumerate(master_out.columns):
                vals = master_out[col].astype(str).head(2000).tolist()
                width = min(max([len(str(col))] + [len(v) for v in vals]) + 2, 40)
                ws1.set_column(i, i, width)

            idx = {c: i for i, c in enumerate(master_out.columns)}
            s_col = idx["SOURCE"]
            present_col = idx["__SRC_PRESENT"]
            n_rows, n_cols = master_out.shape

            for r in range(n_rows):
                src = str(master_out.iat[r, s_col]).strip().upper()
                present_all = int(master_out.iat[r, present_col]) >= 3
                base_fmt, warn_fmt = (fmt_bb, fmt_bb_warn)
                if src == "RED":
                    base_fmt, warn_fmt = (fmt_red, fmt_red_warn)
                elif src == "SR":
                    base_fmt, warn_fmt = (fmt_sr, fmt_sr_warn)
                fmt = base_fmt if present_all else warn_fmt
                for c in range(n_cols):
                    ws1.write(r + 1, c, master_out.iat[r, c], fmt)

            # Summary sheet
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

        # ─────────────────────────────────────────────────────
        # TIMESTAMPED FILENAME – MATCH GOOD PATTERN
        # ─────────────────────────────────────────────────────
        eastern = pytz.timezone("America/New_York")
        ts = datetime.now(eastern).strftime("%y%m%d_%H%M")
        file_name = f"{ts}_Master_Students.xlsx"

        st.success("✅ Master_Students workbook generated")
        st.download_button(
            label=f"⬇️ Download {file_name}",
            data=output.getvalue(),
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
