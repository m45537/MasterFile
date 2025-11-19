import io
import re
import pandas as pd
import streamlit as st

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG (must be the first Streamlit call, and only once)
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Roster → Master (LENIENT)", page_icon="📘", layout="centered")

st.title("📘 Master Students Builder — Lenient")
st.caption("Upload Blackbaud, Rediker, and Student Records → get a styled Excel with Master + Summary tabs.")

# ──────────────────────────────────────────────────────────────────────────────
# NORMALIZATION HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def norm_piece(s: str) -> str:
    # Allow letters, digits, spaces, hyphens; uppercase; trim
    return re.sub(r"[^A-Z0-9 \-]+", "", str(s).upper()).strip()

def grade_norm(s: str) -> str:
    x = norm_piece(s)
    x = re.sub(r"\s+", "", x)
    aliases = {
        "P4": "PK4", "PK": "PK4", "PREK": "PK4", "PREK4": "PK4", "PRE-K": "PK4", "PRE-K4": "PK4",
        "P3": "PK3", "PREK3": "PK3", "PRE-K3": "PK3",
        "KINDERGARTEN": "K", "KINDER": "K", "KG": "K"
    }
    if x in aliases:
        return aliases[x]
    m = re.fullmatch(r"(GRADE|GR|G)?(\d{1,2})", x)
    if m:
        return str(int(m.group(2)))
    return x

def surname_last_token(last: str) -> str:
    # Use the LAST token of the last name to handle compound surnames (ABREU RAMIREZ → RAMIREZ)
    s = norm_piece(last).replace("-", " ")
    toks = [t for t in s.split() if t]
    return toks[-1] if toks else ""

def firstname_first_token(first: str, last: str) -> str:
    # Prefer first token of FIRST name; if missing, fall back to first token of LAST
    ftoks = [t for t in norm_piece(first).split() if t]
    if ftoks:
        return ftoks[0]
    ltoks = [t for t in norm_piece(last).split() if t]
    return ltoks[0] if ltoks else ""

def make_unique_key_lenient(first: str, last: str, grade: str) -> str:
    return f"{surname_last_token(last)}|{firstname_first_token(first, last)}|{grade_norm(grade)}"

# ──────────────────────────────────────────────────────────────────────────────
# GENERIC COLUMN-FINDING UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def upper_cols(df):
    return {str(c).strip().upper(): c for c in df.columns}

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
    # Prefer columns that explicitly include both STUDENT and GRADE
    for c in df.columns:
        up = str(c).strip().upper()
        if "STUDENT" in up and "GRADE" in up:
            return c
    # Fallback: a column with many "(...)" endings (e.g., "LAST, FIRST (K)")
    scores = {c: df[c].astype(str).str.contains(r"\([^)]+\)\s*$", regex=True).sum() for c in df.columns}
    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else None

# ──────────────────────────────────────────────────────────────────────────────
# BLACKBAUD PARSER (robust header detection; parent columns OPTIONAL)
# ──────────────────────────────────────────────────────────────────────────────
def parse_blackbaud(file) -> pd.DataFrame:
    # Detect header row in first 25 lines
    probe = pd.read_excel(file, header=None, nrows=25)
    want = ["FAMILY", "ID", "PARENT", "FIRST", "LAST", "STUDENT", "GRADE"]
    best_row, best_hits = 0, -1
    for i in range(len(probe)):
        row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
        hits = sum(w in row for w in want)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row).fillna("")
    df.columns = [str(c).strip() for c in df.columns]

    # Flexible column finding
    fam_col = find_any(df, ("FAMILY","ID"))
    # Parent FIRST/LAST: accept broad variants and make OPTIONAL
    pf_col = find_any(
        df, ("PARENT","FIRST"),
        ("PARENT 1","FIRST"), ("P1","FIRST"),
        ("PRIMARY","PARENT","FIRST"),
        ("GUARDIAN","FIRST"),
        ("CONTACT 1","FIRST"), ("CONTACT1","FIRST")
    )
    pl_col = find_any(
        df, ("PARENT","LAST"),
        ("PARENT 1","LAST"), ("P1","LAST"),
        ("PRIMARY","PARENT","LAST"),
        ("GUARDIAN","LAST"),
        ("CONTACT 1","LAST"), ("CONTACT1","LAST")
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
        fam = str(r.get(fam_col, "")).replace(".0","").strip() if fam_col else ""
        pf  = str(r.get(pf_col,  "")).strip() if pf_col else ""
        pl  = str(r.get(pl_col,  "")).strip() if pl_col else ""
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
# REDIKER PARSER (robust; grade tolerant/inferred; required FIRST/LAST only)
# ──────────────────────────────────────────────────────────────────────────────
def parse_rediker(file) -> pd.DataFrame:
    probe = pd.read_excel(file, header=None, nrows=12, usecols="A:K")
    tokens = {"APID","UNIQUE","STUDENT","FIRST","LAST","GRADE","LEVEL","GR","FAMILY","ID","HOMEROOM","SECTION","CLASS","HR"}
    best_row, best_hits = 0, -1
    for i in range(len(probe)):
        row_vals = [str(x).strip().upper() for x in probe.iloc[i].tolist()]
        hits = sum(any(tok in cell for tok in tokens) for cell in row_vals)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row, usecols="A:K").fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    U = {c.upper().strip(): c for c in df.columns}

    first_col = next((U[k] for k in U if k in ("FIRST","FIRST NAME","FIRST_NAME","STUDENT FIRST NAME")), None)
    last_col  = next((U[k] for k in U if k in ("LAST","LAST NAME","LAST_NAME","STUDENT LAST NAME")), None)
    name_col  = next((U[k] for k in U if k in ("STUDENT NAME","STUDENT_NAME","NAME")), None)

    # Grade detection (tolerant)
    grade_keys = (
        "GRADE","GRADE LEVEL","GRADELEVEL","GR","GR LEVEL","GRLEVEL","GRADE_LVL",
        "GRADE(LVL)","GRADE (LEVEL)","CURRENT GRADE","CUR GRADE","LVL"
    )
    grade_col = None
    for k in U:
        kk = " ".join(k.split())
        if kk in grade_keys or ("GRADE" in kk and "FAMILY" not in kk):
            grade_col = U[k]; break

    fam_col = next((U[k] for k in U if "FAMILY" in k and "ID" in k), None)
    rid_col = next((U[k] for k in U if k in ("APID","UNIQUE ID","UNIQUE_ID","REDIKER ID","REDIKERID","ID") and U[k] != fam_col), None)

    def split_student_name(val: str):
        if pd.isna(val) or str(val).strip() == "":
            return "", ""
        s = str(val).strip()
        if ";" in s:
            last, first = [t.strip() for t in s.split(";",1)]
        elif "," in s:
            last, first = [t.strip() for t in s.split(",",1)]
        else:
            parts = s.split()
            last, first = (parts[0], " ".join(parts[1:])) if len(parts) >= 2 else (s, "")
        return first, last

    if not (first_col and last_col) and name_col:
        split = df[name_col].apply(split_student_name).tolist()
        df["__First"], df["__Last"] = zip(*split) if split else ([], [])
        first_col, last_col = "__First", "__Last"

    # Try to infer grade if column absent
    inferred_grade = None
    if not grade_col:
        likely_grade_sources = []
        for c in df.columns:
            up = c.upper()
            if any(key in up for key in ("HOMEROOM","HOMEROOM#", "HR", "SECTION","CLASS","GRADE")):
                likely_grade_sources.append(c)

        def guess_grade_from_text(s: str) -> str:
            if not s or str(s).strip()=="":
                return ""
            t = norm_piece(s)
            if re.search(r"\bP\s*3\b|PK\s*3\b|PRE[-\s]*K\s*3\b|PREK\s*3\b", t):
                return "PK3"
            if re.search(r"\bP\s*4\b|PK\s*4\b|PRE[-\s]*K\s*4\b|PREK\s*4\b", t):
                return "PK4"
            if re.search(r"\bK(\b|INDER)", t):
                return "K"
            m = re.search(r"\b(?:GR|GRADE|G)?\s*([1-9]|1[0-2])\b", t)
            if m:
                return str(int(m.group(1)))
            m = re.search(r"\b([1-9]|1[0-2])\s*[-]?[A-Z]\b", t)
            if m:
                return str(int(m.group(1)))
            return ""

        for c in likely_grade_sources:
            series_guess = df[c].astype(str).apply(guess_grade_from_text)
            if (series_guess != "").mean() >= 0.25:
                inferred_grade = series_guess
                break
        if inferred_grade is None:
            for c in df.columns:
                series_guess = df[c].astype(str).apply(guess_grade_from_text)
                if (series_guess != "").mean() >= 0.25:
                    inferred_grade = series_guess
                    break

        if inferred_grade is None:
            st.warning("Rediker: no GRADE column found and could not infer grades. Proceeding with blanks.")
        else:
            st.info("Rediker: GRADE column not found; grades inferred from other columns.")

    # Guard names (we’ll proceed even if grade blank)
    if not first_col or not last_col:
        st.error("Rediker: couldn’t find required column(s): FIRST name and/or LAST name.")
        st.stop()

    rows = []
    for idx, r in df.iterrows():
        fam   = str(r.get(fam_col, "")).replace(".0","").strip() if fam_col else ""
        rid   = str(r.get(rid_col, "")).replace(".0","").strip() if rid_col else ""
        first = str(r.get(first_col, "")).strip()
        last  = str(r.get(last_col,  "")).strip()
        if grade_col:
            grade = str(r.get(grade_col, "")).strip()
        else:
            grade = str(inferred_grade.loc[idx]).strip() if inferred_grade is not None else ""
        rows.append({
            "ID": "",
            "FAMILY ID": fam,
            "PARENT FIRST NAME": "",
            "PARENT LAST NAME": "",
            "STUDENT FIRST NAME": first,
            "STUDENT LAST NAME": last,
            "GRADE": grade,
            "REDIKER ID": rid,
            "SOURCE": "RED",
            "UNIQUE_KEY": make_unique_key_lenient(first, last, grade),
        })
    return pd.DataFrame(rows)

# ──────────────────────────────────────────────────────────────────────────────
# STUDENT RECORDS PARSER (NOW TOLERANT; will not stop; infers/splits NAME)
# ──────────────────────────────────────────────────────────────────────────────
def parse_student_records(file) -> pd.DataFrame:
    # Detect a plausible header row (some SR exports have leading banners)
    probe = pd.read_excel(file, header=None, nrows=20)
    clues = ["STUDENT","FIRST","LAST","NAME","GRADE","FAMILY","REDIKER","ID"]
    best_row, best_hits = 0, -1
    for i in range(len(probe)):
        row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
        hits = sum(cl in row for cl in clues)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row).fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    U = {c.upper(): c for c in df.columns}

    # Try many variants for each field
    col_id   = list(df.columns)[0] if len(df.columns) else None
    col_fam  = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    col_red  = U.get("REDIKER ID") or U.get("REDIKERID") or U.get("REDIKER_ID")
    # First/Last name direct hits
    col_sf   = U.get("STUDENT FIRST NAME") or U.get("FIRST NAME") or U.get("FIRST") or U.get("LEGAL FIRST") or U.get("PREFERRED FIRST")
    col_sl   = U.get("STUDENT LAST NAME")  or U.get("LAST NAME")  or U.get("LAST")  or U.get("LEGAL LAST")
    # Single NAME column variants
    name_col = U.get("STUDENT NAME") or U.get("NAME") or U.get("FULL NAME") or U.get("CHILD NAME") or U.get("STUDENT")

    # Grade
    col_grade= U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR") or U.get("CURRENT GRADE")

    # If FIRST/LAST missing but NAME exists, split it
    def split_name_cell(val: str):
        if pd.isna(val) or str(val).strip()=="":
            return "", ""
        s = str(val).strip()
        if ";" in s:
            last, first = [t.strip() for t in s.split(";",1)]
        elif "," in s:
            last, first = [t.strip() for t in s.split(",",1)]
        else:
            toks = s.split()
            # Prefer "FIRST LAST" for SR single-column names
            if len(toks) >= 2:
                first = " ".join(toks[:-1])
                last  = toks[-1]
            elif len(toks) == 1:
                first, last = toks[0], ""
            else:
                first, last = "", ""
        return first, last

    if (not col_sf or not col_sl) and name_col:
        split = df[name_col].apply(split_name_cell).tolist()
        df["__First"], df["__Last"] = zip(*split) if split else ([], [])
        col_sf, col_sl = "__First", "__Last"

    # Last resort: guess a NAME-like column by content (alphabetic and spaces)
    if not (col_sf and col_sl):
        namey = None
        best_score = -1
        for c in df.columns:
            series = df[c].astype(str)
            # score: proportion that looks like alphabetic names with at least one space
            score = ((series.str.contains(r"[A-Za-z]") & series.str.contains(r"\s")).mean())
            if score > best_score:
                best_score, namey = score, c
        if namey and best_score >= 0.3:
            split = df[namey].apply(split_name_cell).tolist()
            df["__First2"], df["__Last2"] = zip(*split) if split else ([], [])
            col_sf, col_sl = "__First2", "__Last2"

    # If STILL missing both names, proceed with blanks (but warn)
    missing_name = not (col_sf and col_sl)
    if missing_name:
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
        "PARENT LAST NAME":  df[U.get("PARENT LAST NAME")].astype(str).str.strip() if U.get("PARENT LAST NAME") else "",
        "STUDENT FIRST NAME": df[col_sf].astype(str).str.strip(),
        "STUDENT LAST NAME":  df[col_sl].astype(str).str.strip(),
        "GRADE": df[col_grade].astype(str).str.strip(),
        "REDIKER ID": df[col_red].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_red else "",
        "SOURCE": "SR",
    })

    # Drop rows where both first and last are blank (we can’t build a key)
    before = len(out)
    out = out[~((out["STUDENT FIRST NAME"]=="") & (out["STUDENT LAST NAME"]==""))].copy()
    dropped = before - len(out)
    if dropped > 0:
        st.warning(f"Student Records: dropped {dropped} row(s) with no usable student name.")

    out["UNIQUE_KEY"] = [make_unique_key_lenient(f, l, g) for f, l, g in zip(out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"])]
    return out

# ──────────────────────────────────────────────────────────────────────────────
# UI — UPLOADS
# ──────────────────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    f_bb = st.file_uploader("Blackbaud", type=["xlsx","xls"])
with col2:
    f_red = st.file_uploader("Rediker", type=["xlsx","xls"])
with col3:
    f_sr = st.file_uploader("Student Records", type=["xlsx","xls"])

run = st.button("Build Master Excel", type="primary", disabled=not (f_bb and f_red and f_sr))

# ──────────────────────────────────────────────────────────────────────────────
# PROCESS
# ──────────────────────────────────────────────────────────────────────────────
if run:
    with st.spinner("Parsing & normalizing..."):
        bb_df  = parse_blackbaud(f_bb)
        red_df = parse_rediker(f_red)
        sr_df  = parse_student_records(f_sr)

    TARGET = [
        "ID","FAMILY ID","PARENT FIRST NAME","PARENT LAST NAME",
        "STUDENT FIRST NAME","STUDENT LAST NAME","GRADE","REDIKER ID","SOURCE","UNIQUE_KEY"
    ]
    master = pd.concat([bb_df[TARGET], red_df[TARGET], sr_df[TARGET]], ignore_index=True)

    # Build helpers for lenient grouping/presence (STRICTER: surname token + first token + normalized grade)
    master["__SURNAME"]  = master["STUDENT LAST NAME"].apply(surname_last_token)
    master["__FIRSTTOK"] = master.apply(lambda r: firstname_first_token(r["STUDENT FIRST NAME"], r["STUDENT LAST NAME"]), axis=1)
    master["__GRADELEN"] = master["GRADE"].apply(grade_norm)

    # Presence counted on SURNAME+FIRSTTOKEN+GRADE
    master["__GROUP_KEY"] = master["__SURNAME"] + "|" + master["__FIRSTTOK"] + "|" + master["__GRADELEN"]

    src_counts = master.groupby("__GROUP_KEY")["SOURCE"].nunique().to_dict()
    master["__SRC_PRESENT"] = master["__GROUP_KEY"].map(src_counts).fillna(0).astype(int)

    # Sort by key then source
    order = {"BB":0, "RED":1, "SR":2}
    master["_source_rank"] = master["SOURCE"].map(lambda x: order.get(str(x).upper(), 99))
    master["UNIQUE_KEY"] = master["__SURNAME"] + "|" + master["__FIRSTTOK"] + "|" + master["__GRADELEN"]
    master_sorted = master.sort_values(by=["UNIQUE_KEY","_source_rank","STUDENT LAST NAME","STUDENT FIRST NAME"], kind="mergesort").reset_index(drop=True)

    # SUMMARY (on the stricter GROUP_KEY)
    summary_rows = []
    for gkey, grp in master.groupby("__GROUP_KEY"):
        parts = gkey.split("|")
        surname_token, first_token, grade = (parts + ["",""])[:3]
        in_bb  = any(grp["SOURCE"].str.upper()=="BB")
        in_red = any(grp["SOURCE"].str.upper()=="RED")
        in_sr  = any(grp["SOURCE"].str.upper()=="SR")
        summary_rows.append({
            "SURNAME_TOKEN(LAST)": surname_token,
            "FIRST_TOKEN": first_token,
            "GRADE": grade,
            "BB": "✅" if in_bb else "❌",
            "RED": "✅" if in_red else "❌",
            "SR": "✅" if in_sr else "❌",
            "SOURCES_PRESENT": int(in_bb)+int(in_red)+int(in_sr),
        })
    summary = pd.DataFrame(summary_rows).sort_values(["SURNAME_TOKEN(LAST)","GRADE","FIRST_TOKEN"]).reset_index(drop=True)

    # ── Presence-by-key debug
    with st.expander("Presence by key (debug)"):
        debug = (master
                 .groupby("__GROUP_KEY")
                 .agg(SOURCES_PRESENT=("SOURCE", lambda s: s.str.upper().nunique()),
                      SOURCES=("SOURCE", lambda s: ",".join(sorted(set(s.str.upper())))),
                      EXAMPLE_NAMES=("STUDENT FIRST NAME", lambda s: "; ".join(s.head(3).astype(str)))))
        st.dataframe(debug.sort_values("SOURCES_PRESENT", ascending=False).head(200))

        all3 = master[master["__GROUP_KEY"].isin(debug.index[debug["SOURCES_PRESENT"]==3])]
        st.write(f"Rows present in all 3 sources: {len(all3)}")
        st.dataframe(all3[["SOURCE","STUDENT LAST NAME","STUDENT FIRST NAME","GRADE","UNIQUE_KEY"]].head(50))

        st.download_button(
            "Download presence_debug.csv",
            data=debug.to_csv().encode("utf-8"),
            file_name="presence_debug.csv",
            mime="text/csv"
        )

    # WRITE EXCEL (+ styling: highlight only when __SRC_PRESENT < 3)
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
            vals = master_sorted[col].astype(str).head(2000).tolist()
            width = min(max([len(str(col))] + [len(v) for v in vals]) + 2, 40)
            ws1.set_column(i, i, width)
        idx = {c:i for i,c in enumerate(master_sorted.columns)}
        s_col = idx["SOURCE"]; present_col = idx["__SRC_PRESENT"]
        n_rows, n_cols = master_sorted.shape
        for r in range(n_rows):
            src = str(master_sorted.iat[r, s_col]).strip().upper()
            present_all = int(master_sorted.iat[r, present_col]) >= 3
            base_fmt, warn_fmt = (fmt_bb, fmt_bb_warn)
            if src == "RED": base_fmt, warn_fmt = (fmt_red, fmt_red_warn)
            elif src == "SR": base_fmt, warn_fmt = (fmt_sr, fmt_sr_warn)
            fmt = base_fmt if present_all else warn_fmt  # only highlight if NOT in all 3
            for c in range(n_cols):
                ws1.write(r + 1, c, master_sorted.iat[r, c], fmt)
        # hide helpers
        for helper in ["__SURNAME","__FIRSTTOK","__GRADELEN","__GROUP_KEY","__SRC_PRESENT","_source_rank"]:
            if helper in idx:
                ws1.set_column(idx[helper], idx[helper], None, None, {"hidden": True})

        # Sheet 2: Summary
        summary.to_excel(writer, index=False, sheet_name="Summary")
        ws2 = writer.sheets["Summary"]
        header_fmt2 = wb.add_format({"bold": True})
        ok_fmt  = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100"})
        bad_fmt = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
        for c_idx, col in enumerate(summary.columns):
            ws2.write(0, c_idx, col, header_fmt2)
        for i, col in enumerate(summary.columns):
            vals = summary[col].astype(str).head(2000).tolist()
            width = min(max([len(str(col))] + [len(v) for v in vals]) + 2, 50)
            ws2.set_column(i, i, width)
        col_idx = {c:i for i,c in enumerate(summary.columns)}
        for r in range(len(summary)):
            for src_col in ["BB","RED","SR"]:
                val = summary.iat[r, col_idx[src_col]]
                ws2.write(r + 1, col_idx[src_col], val, ok_fmt if val == "✅" else bad_fmt)

    st.success("✅ Excel generated successfully")
    st.download_button(
        label="⬇️ Download Master_Students_Combined_LENIENT_WITH_SUMMARY.xlsx",
        data=output.getvalue(),
        file_name="Master_Students_Combined_LENIENT_WITH_SUMMARY.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
