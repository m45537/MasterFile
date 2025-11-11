import io, re
import pandas as pd
import streamlit as st

# ------------------------------
# App config
# ------------------------------
st.set_page_config(page_title="Roster → Master (LENIENT)", page_icon="📘", layout="centered")
st.title("📘 Master Students Builder — Lenient")
st.caption("Upload Blackbaud, Rediker, Student Records → get a styled Excel with Master + Summary tabs.")

# ------------------------------
# Helpers (normalization & parsing)
# ------------------------------

def norm_piece(s: str) -> str:
    return re.sub(r"[^A-Z0-9 ]+", "", str(s).upper()).strip()

def grade_norm(s: str) -> str:
    """Normalize grade labels to consistent keys used for matching."""
    x = norm_piece(s)
    x = re.sub(r"\s+", "", x)

    # Common aliases & typos
    aliases = {
        # Pre-K
        "P4": "PK4", "PK": "PK4", "PREK": "PK4", "PREK4": "PK4", "PRE-K": "PK4", "PRE-K4": "PK4",
        "P3": "PK3", "PREK3": "PK3", "PRE-K3": "PK3",
        # Kindergarten
        "KINDERGARTEN": "K", "KINDER": "K", "KG": "K", "0K": "K",
        "KINDERGARDEN": "K",  # occasional typo
    }
    if x in aliases:
        return aliases[x]

    # Grade numbers like: 1, 02, G2, GR3, GRADE4, "Grade 5", "5th", "2nd Grade", etc.
    m = re.fullmatch(r"(GRADE|GR|G)?(\d{1,2})", x)
    if m:
        return str(int(m.group(2)))  # strip leading zeroes

    # Fallback: if any digits appear, take the first number
    m2 = re.search(r"(\\d{1,2})", x)
    if m2:
        return str(int(m2.group(1)))

    # Leave PK3/PK4/K and other non-numeric codes as-is
    return x

def surname_first_token(last: str) -> str:
    tokens = [t for t in norm_piece(last).split() if t]
    return tokens[0] if tokens else ""

def firstname_first_token(first: str, last: str) -> str:
    ftoks = [t for t in norm_piece(first).split() if t]
    if ftoks:
        return ftoks[0]
    ltoks = [t for t in norm_piece(last).split() if t]
    return ltoks[1] if len(ltoks) >= 2 else (ltoks[0] if ltoks else "")

def make_unique_key_lenient(first: str, last: str, grade: str) -> str:
    return f"{surname_first_token(last)}|{firstname_first_token(first, last)}|{grade_norm(grade)}"

# ---------- Blackbaud parsing: robust detection for "Student name and grades" ----------
def parse_blackbaud(file) -> pd.DataFrame:
    df = pd.read_excel(file)  # read all columns; some exports shift columns
    U = {str(c).strip().upper(): c for c in df.columns}

    col_fam  = U.get("FAMILY ID") or next((c for k,c in U.items() if "FAMILY" in k and "ID" in k), None)
    col_pf   = U.get("PARENT FIRST NAME") or U.get("FIRST NAME") or U.get("PARENT FIRST")
    col_pl   = U.get("PARENT LAST NAME")  or U.get("LAST NAME")  or U.get("PARENT LAST")

    # look for any column that contains both "STUDENT NAME" and "GRADE"
    col_stu = next((c for k,c in U.items() if "STUDENT NAME" in k and "GRADE" in k), None)

    if not col_stu:
        st.warning("Blackbaud: could not find a 'Student name and grades' column. Proceeding with blanks.")
    if not col_pf or not col_pl:
        st.info("Blackbaud: Parent First/Last columns not found. Proceeding with blanks for those fields.")

    def split_students(cell: str):
        if pd.isna(cell) or str(cell).strip()== "":
            return []
        text = str(cell)
        text = re.sub(r"\\s*\\)\\s*[,/;|]?\\s*", ")|", text)  # normalize separators after ')'
        parts = [p.strip().rstrip(",;/|") for p in text.split("|") if p.strip()]
        return parts

    def parse_student_entry(entry: str):
        m = re.search(r"\\(([^)]+)\\)\\s*$", entry)
        grade = m.group(1).strip() if m else ""
        name = re.sub(r"\\([^)]+\\)\\s*$", "", entry).strip()
        if ";" in name:
            last, first = [t.strip() for t in name.split(";", 1)]
        elif "," in name:
            last, first = [t.strip() for t in name.split(",", 1)]
        else:
            toks = name.split()
            if len(toks) >= 2:
                last, first = " ".join(toks[:-1]), toks[-1]
            else:
                last, first = name, ""
        return last, first, grade

    rows = []
    for _, r in df.iterrows():
        fam = str(r.get(col_fam, "")).replace(".0","" ).strip() if col_fam else ""
        pf  = str(r.get(col_pf, "")).strip() if col_pf else ""
        pl  = str(r.get(col_pl, "")).strip() if col_pl else ""
        for entry in split_students(r.get(col_stu, "")):
            stu_last, stu_first, grade = parse_student_entry(entry)
            rows.append({
                "ID": "",
                "FAMILY ID": fam,
                "PARENT FIRST NAME": pf,
                "PARENT LAST NAME": pl,
                "STUDENT FIRST NAME": stu_first,
                "STUDENT LAST NAME": stu_last,
                "GRADE": grade,
                "REDIKER ID": "",
                "SOURCE": "BB",
                "UNIQUE_KEY": make_unique_key_lenient(stu_first, stu_last, grade),
            })
    return pd.DataFrame(rows)

# ---------- Rediker parsing: detect header row and flexible grade/first/last ----------
def parse_rediker(file) -> pd.DataFrame:
    preview = pd.read_excel(file, header=None, nrows=12)
    candidates = {"APID","UNIQUE ID","STUDENT NAME","FIRST","LAST","GRADE","GRADE LEVEL","GR"}
    best_row, best_hits = 0, -1
    for i in range(len(preview)):
        row_vals = [str(x).strip().upper() for x in preview.iloc[i].tolist()]
        hits = sum(any((c in cell) or (c == cell) for c in candidates) for cell in row_vals)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row).fillna("")
    U = {str(c).strip().upper(): c for c in df.columns}

    first_col = U.get("FIRST") or U.get("FIRST NAME") or None
    last_col  = U.get("LAST")  or U.get("LAST NAME")  or None
    name_col  = U.get("STUDENT NAME") or U.get("NAME") or None
    grade_col = U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR") or U.get("GRD") or None

    # Build first/last from name if needed
    if (not first_col or not last_col) and name_col:
        def split_student_name(val: str):
            if pd.isna(val) or str(val).strip()== "":
                return "", ""
            s = str(val).strip()
            if ";" in s:
                last, first = [t.strip() for t in s.split(";",1)]
            elif "," in s:
                last, first = [t.strip() for t in s.split(",",1)]
            else:
                parts = s.split()
                last, first = (" ".join(parts[:-1]), parts[-1]) if len(parts)>=2 else (s, "")
            return first, last
        split = df[name_col].apply(split_student_name).tolist()
        df["__First" ] = [a for a,b in split]
        df["__Last"  ] = [b for a,b in split]
        first_col, last_col = "__First", "__Last"

    if not grade_col:
        st.info("Rediker: no GRADE column found and could not infer grades. Proceeding with blanks.")

    rows = []
    for _, r in df.iterrows():
        first = str(r.get(first_col, "")).strip() if first_col else ""
        last  = str(r.get(last_col,  "")).strip() if last_col  else ""
        grade = str(r.get(grade_col, "")).strip() if grade_col else ""
        rows.append({
            "ID": "",
            "FAMILY ID": "",
            "PARENT FIRST NAME": "",
            "PARENT LAST NAME":  "",
            "STUDENT FIRST NAME": first,
            "STUDENT LAST NAME":  last,
            "GRADE": grade,
            "REDIKER ID": str(r.get(U.get("APID") or U.get("UNIQUE ID") or "ID", "")).replace(".0","").strip(),
            "SOURCE": "RED",
            "UNIQUE_KEY": make_unique_key_lenient(first, last, grade),
        })
    return pd.DataFrame(rows)

# ---------- Student Records parsing: accept CHILD FIRST/LAST or split NAME ----------
def parse_student_records(file) -> pd.DataFrame:
    df = pd.read_excel(file).fillna("")
    U = {str(c).strip().upper(): c for c in df.columns}
    col_id = list(df.columns)[0]
    col_fam = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    col_red = U.get("REDIKER ID") or U.get("REDIKERID") or U.get("REDIKER_ID") or U.get("REDIKER ID#")
    col_pf  = U.get("PARENT FIRST NAME") or U.get("PARENT FIRST") or U.get("FIRST PARENT NAME")
    col_pl  = U.get("PARENT LAST NAME")  or U.get("PARENT LAST")  or U.get("LAST PARENT NAME")
    col_sf  = U.get("CHILD FIRST NAME") or U.get("STUDENT FIRST NAME") or U.get("FIRST NAME") or U.get("FIRST")
    col_sl  = U.get("CHILD LAST NAME")  or U.get("STUDENT LAST NAME")  or U.get("LAST NAME")  or U.get("LAST")
    col_grade = U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR")

    # If first/last not present, try to split student/child name
    if (not col_sf or not col_sl) and ("STUDENT NAME" in U or "CHILD NAME" in U or "NAME" in U):
        name_col = U.get("STUDENT NAME") or U.get("CHILD NAME") or U.get("NAME")
        def split_student_name(val: str):
            if pd.isna(val) or str(val).strip()== "":
                return "", ""
            s = str(val).strip()
            if ";" in s:
                last, first = [t.strip() for t in s.split(";",1)]
            elif "," in s:
                last, first = [t.strip() for t in s.split(",",1)]
            else:
                parts = s.split()
                last, first = (" ".join(parts[:-1]), parts[-1]) if len(parts)>=2 else (s, "")
            return first, last
        split = df[name_col].apply(split_student_name).tolist()
        df["__First"] = [a for a,b in split]
        df["__Last" ] = [b for a,b in split]
        col_sf, col_sl = "__First", "__Last"

    if not col_sf or not col_sl:
        st.info("Student Records: couldn’t find required column(s): FIRST name, LAST name. Proceeding with blanks if needed.")

    out = pd.DataFrame({
        "ID": df[col_id].astype(str).str.replace(r"\\.0$", "", regex=True).str.strip() if col_id else "",
        "FAMILY ID": df[col_fam].astype(str).str.replace(r"\\.0$", "", regex=True).str.strip() if col_fam else "",
        "PARENT FIRST NAME": df[col_pf].astype(str).str.strip() if col_pf else "",
        "PARENT LAST NAME":  df[col_pl].astype(str).str.strip() if col_pl else "",
        "STUDENT FIRST NAME": df[col_sf].astype(str).str.strip() if col_sf else "",
        "STUDENT LAST NAME":  df[col_sl].astype(str).str.strip() if col_sl else "",
        "GRADE": df[col_grade].astype(str).str.strip() if col_grade else "",
        "REDIKER ID": df[col_red].astype(str).str.replace(r"\\.0$", "", regex=True).str.strip() if col_red else "",
        "SOURCE": "SR",
    })
    out["UNIQUE_KEY"] = [make_unique_key_lenient(f, l, g) for f, l, g in zip(out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"])]
    return out

# ------------------------------
# UI: Uploads
# ------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    f_bb = st.file_uploader("Blackbaud (any export: must contain 'Student name and grades' column)", type=["xlsx","xls"])  
with col2:
    f_red = st.file_uploader("Rediker (header auto-detected)", type=["xlsx","xls"])  
with col3:
    f_sr = st.file_uploader("Student Records", type=["xlsx","xls"])  

run = st.button("Build Master Excel", type="primary", disabled=not (f_bb and f_red and f_sr))

# ------------------------------
# Action
# ------------------------------
if run:
    with st.spinner("Parsing & normalizing..."):
        try:
            bb_df  = parse_blackbaud(f_bb)
            red_df = parse_rediker(f_red)
            sr_df  = parse_student_records(f_sr)
        except Exception as e:
            st.error(f"Error while reading files: {e}")
            st.stop()

    TARGET_COLS = [
        "ID","FAMILY ID","PARENT FIRST NAME","PARENT LAST NAME",
        "STUDENT FIRST NAME","STUDENT LAST NAME","GRADE","REDIKER ID","SOURCE"
    ]
    for df in (bb_df, red_df, sr_df):
        for c in TARGET_COLS:
            if c not in df.columns:
                df[c] = ""
        df = df[TARGET_COLS]

    master = pd.concat([bb_df[TARGET_COLS], red_df[TARGET_COLS], sr_df[TARGET_COLS]], ignore_index=True)

    # Build helpers for lenient grouping/presence
    master["__SURNAME"] = master["STUDENT LAST NAME"].apply(surname_first_token)
    master["__FIRSTTOK"] = master.apply(lambda r: firstname_first_token(r["STUDENT FIRST NAME"], r["STUDENT LAST NAME"]), axis=1)
    master["__GRADELEN"] = master["GRADE"].apply(grade_norm)
    master["UNIQUE_KEY"] = master["__SURNAME"] + "|" + master["__FIRSTTOK"] + "|" + master["__GRADELEN"]
    master["__GROUP_KEY"] = master["__SURNAME"] + "|" + master["__GRADELEN"]

    src_counts = master.groupby("__GROUP_KEY")["SOURCE"].nunique().to_dict()
    master["__SRC_PRESENT"] = master["__GROUP_KEY"].map(src_counts).fillna(0).astype(int)

    # Sort by unique key then source
    source_order = {"BB":0, "RED":1, "SR":2}
    master["_source_rank"] = master["SOURCE"].map(lambda x: source_order.get(str(x).upper(), 99))
    master_sorted = master.sort_values(by=["UNIQUE_KEY","_source_rank","STUDENT LAST NAME","STUDENT FIRST NAME"], kind="mergesort").reset_index(drop=True)

    # Build Summary sheet
    from collections import Counter
    summary_rows = []
    grouped = master.groupby("__GROUP_KEY")
    for gkey, grp in grouped:
        surname, grade = gkey.split("|", 1)
        first_tokens = [t for t in grp["__FIRSTTOK"].tolist() if t]
        first_common = Counter(first_tokens).most_common(1)[0][0] if first_tokens else ""
        in_bb  = any(grp["SOURCE"].str.upper() == "BB")
        in_red = any(grp["SOURCE"].str.upper() == "RED")
        in_sr  = any(grp["SOURCE"].str.upper() == "SR")
        present_count = int(in_bb) + int(in_red) + int(in_sr)
        raw_bb  = [f"{r['STUDENT LAST NAME']} {r['STUDENT FIRST NAME']}" for _, r in grp.iterrows() if str(r["SOURCE"]).upper()=="BB"]
        raw_red = [f"{r['STUDENT LAST NAME']} {r['STUDENT FIRST NAME']}" for _, r in grp.iterrows() if str(r["SOURCE"]).upper()=="RED"]
        raw_sr  = [f"{r['STUDENT LAST NAME']} {r['STUDENT FIRST NAME']}" for _, r in grp.iterrows() if str(r["SOURCE"]).upper()=="SR"]
        summary_rows.append({
            "SURNAME": surname,
            "FIRST": first_common,
            "GRADE": grade,
            "BB": "✅" if in_bb else "❌",
            "RED": "✅" if in_red else "❌",
            "SR": "✅" if in_sr else "❌",
            "SOURCES_PRESENT": present_count,
            "RAW_NAMES_BB": "; ".join(raw_bb),
            "RAW_NAMES_RED": "; ".join(raw_red),
            "RAW_NAMES_SR": "; ".join(raw_sr),
        })
    summary = pd.DataFrame(summary_rows).sort_values(["SURNAME","GRADE","FIRST"]).reset_index(drop=True)

    # Write styled Excel in-memory
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
        fmt_bb_warn  = wb.add_format({"font_color": "#000000", "bg_color": warn_fill, "bold": True})
        fmt_red_warn = wb.add_format({"font_color": "#A10000", "bg_color": warn_fill, "bold": True})
        fmt_sr_warn  = wb.add_format({"font_color": "#006400", "bg_color": warn_fill, "bold": True})
        # header
        for c_idx, col in enumerate(master_sorted.columns):
            ws1.write(0, c_idx, col, header_fmt)
        # autosize
        for i, col in enumerate(master_sorted.columns):
            vals = master_sorted[col].head(2000).astype(str).tolist()
            width = min(max([len(str(col))] + [len(v) for v in vals]) + 2, 40)
            ws1.set_column(i, i, width)
        idx = {c:i for i,c in enumerate(master_sorted.columns)}
        s_col = idx["SOURCE"]
        present_col = idx["__SRC_PRESENT"]
        n_rows, n_cols = master_sorted.shape
        for r in range(n_rows):
            src = str(master_sorted.iat[r, s_col]).strip().upper()
            present_all = int(master_sorted.iat[r, present_col]) >= 3
            if src == "RED":
                base_fmt, warn_fmt = fmt_red, fmt_red_warn
            elif src == "SR":
                base_fmt, warn_fmt = fmt_sr, fmt_sr_warn
            else:
                base_fmt, warn_fmt = fmt_bb, fmt_bb_warn
            fmt = base_fmt if present_all else warn_fmt
            for c in range(n_cols):
                ws1.write(r + 1, c, master_sorted.iat[r, c], fmt)
        # hide helpers
        for helper in ["__SURNAME","__FIRSTTOK","__GRADELEN","__GROUP_KEY","__SRC_PRESENT","_source_rank"]:
            if helper in idx:
                ws1.set_column(idx[helper], idx[helper], None, None, {"hidden": True})

        # Sheet 2: Summary (colored ✅/❌)
        summary.to_excel(writer, index=False, sheet_name="Summary")
        ws2 = writer.sheets["Summary"]
        header_fmt2 = wb.add_format({"bold": True})
        ok_fmt = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100"})
        bad_fmt = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
        for c_idx, col in enumerate(summary.columns):
            ws2.write(0, c_idx, col, header_fmt2)
        for i, col in enumerate(summary.columns):
            vals = summary[col].head(2000).astype(str).tolist()
            width = min(max([len(str(col))] + [len(v) for v in vals]) + 2, 50)
            ws2.set_column(i, i, width)
        col_idx = {c:i for i,c in enumerate(summary.columns)}
        for r in range(len(summary)):
            for src_col in ["BB","RED","SR"]:
                val = summary.iat[r, col_idx[src_col]]
                ws2.write(r + 1, col_idx[src_col], val, ok_fmt if val == "✅" else bad_fmt)

    st.success("Done — download your Excel below.")
    st.download_button(
        label="⬇️ Download Master_Students_Combined_LENIENT_WITH_SUMMARY.xlsx",
        data=output.getvalue(),
        file_name="Master_Students_Combined_LENIENT_WITH_SUMMARY.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
