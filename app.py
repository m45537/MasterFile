
import io, re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Roster → Master (LENIENT)", page_icon="📘", layout="centered")
st.title("📘 Master Students Builder — Lenient")
st.caption("Upload Blackbaud, Rediker, Student Records → get a styled Excel with Master + Summary tabs.")

# ------------------------------
# Debug logging toggle (optional)
# ------------------------------
with st.sidebar:
    debug_log = st.checkbox("🪵 Show detailed debug logs", value=False)
    st.caption("When enabled, displays column matches and sample data from uploaded files.")

def norm_piece(s: str) -> str:
    return re.sub(r"[^A-Z0-9 ]+", "", str(s).upper()).strip()

def grade_norm(s: str) -> str:
    x = norm_piece(s)
    x = re.sub(r"\s+", "", x)
    aliases = {
        "P4": "PK4", "PK": "PK4", "PREK": "PK4", "PREK4": "PK4", "PRE-K": "PK4", "PRE-K4": "PK4",
        "P3": "PK3", "PREK3": "PK3", "PRE-K3": "PK3",
        "KINDERGARTEN": "K", "KINDER": "K", "KG": "K", "0K": "K",
        "KINDERGARDEN": "K",
    }
    if x in aliases:
        return aliases[x]
    m = re.fullmatch(r"(GRADE|GR|G)?(\d{1,2})", x)
    if m:
        return str(int(m.group(2)))
    m2 = re.search(r"(\d{1,2})", x)
    if m2:
        return str(int(m2.group(1)))
    return x

def surname_first_token(last: str) -> str:
    toks = [t for t in norm_piece(last).split() if t]
    return toks[0] if toks else ""

def firstname_first_token(first: str, last: str) -> str:
    ftoks = [t for t in norm_piece(first).split() if t]
    if ftoks:
        return ftoks[0]
    ltoks = [t for t in norm_piece(last).split() if t]
    return ltoks[1] if len(ltoks) >= 2 else (ltoks[0] if ltoks else "")

def make_unique_key_lenient(first: str, last: str, grade: str) -> str:
    return f"{surname_first_token(last)}|{firstname_first_token(first, last)}|{grade_norm(grade)}"

def safe_split_students(cell: str):
    if pd.isna(cell) or str(cell).strip() == "":
        return []
    text = str(cell)
    for delim in ["),", ")/", ");", ") /", ") ;", ") ,", ")|"]:
        text = text.replace(delim, ")|")
    parts = [p.strip().rstrip(",;/|") for p in text.split("|") if p.strip()]
    return parts

def parse_blackbaud(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    if debug_log:
        st.write("🖤 Blackbaud columns:", list(df.columns))
        st.dataframe(df.head(5))
    U = {str(c).strip().upper(): c for c in df.columns}
    col_fam  = U.get("FAMILY ID") or next((c for k,c in U.items() if "FAMILY" in k and "ID" in k), None)
    col_pf   = U.get("PARENT FIRST NAME") or U.get("FIRST NAME") or U.get("PARENT FIRST")
    col_pl   = U.get("PARENT LAST NAME")  or U.get("LAST NAME")  or U.get("PARENT LAST")
    col_stu  = next((c for k,c in U.items() if "STUDENT NAME" in k and "GRADE" in k), None)
    if not col_stu:
        st.warning("Blackbaud: could not find 'Student name and grades' column.")
    rows = []
    for _, r in df.iterrows():
        fam = str(r.get(col_fam, "")).replace(".0","" ).strip() if col_fam else ""
        pf  = str(r.get(col_pf, "")).strip() if col_pf else ""
        pl  = str(r.get(col_pl, "")).strip() if col_pl else ""
        for entry in safe_split_students(r.get(col_stu, "")):
            grade = ""
            name = entry
            if "(" in entry and entry.endswith(")"):
                try:
                    grade = entry[entry.rfind("(")+1:entry.rfind(")")].strip()
                    name = entry[:entry.rfind("(")].strip()
                except Exception:
                    pass
            last, first = name, ""
            if ";" in name:
                last, first = [t.strip() for t in name.split(";", 1)]
            elif "," in name:
                last, first = [t.strip() for t in name.split(",", 1)]
            else:
                toks = name.split()
                last, first = (" ".join(toks[:-1]), toks[-1]) if len(toks)>=2 else (name, "")
            rows.append({
                "ID": "",
                "FAMILY ID": fam,
                "PARENT FIRST NAME": pf,
                "PARENT LAST NAME": pl,
                "STUDENT FIRST NAME": first,
                "STUDENT LAST NAME": last,
                "GRADE": grade,
                "REDIKER ID": "",
                "SOURCE": "BB",
                "UNIQUE_KEY": make_unique_key_lenient(first, last, grade),
            })
    return pd.DataFrame(rows)

def parse_rediker(file) -> pd.DataFrame:
    preview = pd.read_excel(file, header=None, nrows=12)
    if debug_log:
        st.write("🔴 Rediker preview (first 12 rows):")
        st.dataframe(preview)
    candidates = {"APID","UNIQUE ID","STUDENT NAME","FIRST","LAST","GRADE","GRADE LEVEL","GR"}
    best_row, best_hits = 0, -1
    for i in range(len(preview)):
        row_vals = [str(x).strip().upper() for x in preview.iloc[i].tolist()]
        hits = sum(any((c in cell) or (c == cell) for c in candidates) for cell in row_vals)
        if hits > best_hits:
            best_row, best_hits = i, hits
    df = pd.read_excel(file, header=best_row).fillna("")
    if debug_log:
        st.write("🔴 Rediker detected header row:", best_row)
        st.write("🔴 Rediker columns:", list(df.columns))
        st.dataframe(df.head(5))
    U = {str(c).strip().upper(): c for c in df.columns}
    first_col = U.get("FIRST") or U.get("FIRST NAME") or None
    last_col  = U.get("LAST")  or U.get("LAST NAME")  or None
    name_col  = U.get("STUDENT NAME") or U.get("NAME") or None
    grade_col = U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR") or None
    if (not first_col or not last_col) and name_col:
        series = df[name_col].astype(str).str.strip()
        split = series.str.split(",", n=1, expand=True)
        if split.shape[1] != 2:
            split = series.str.split(";", n=1, expand=True)
        if split.shape[1] == 2:
            df["__Last"], df["__First"] = split[0].str.strip(), split[1].str.strip()
            first_col, last_col = "__First", "__Last"
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

def parse_student_records(file) -> pd.DataFrame:
    df = pd.read_excel(file).fillna("")
    if debug_log:
        st.write("💚 Student Records columns:", list(df.columns))
        st.dataframe(df.head(5))
    U = {str(c).strip().upper(): c for c in df.columns}
    col_id = list(df.columns)[0]
    col_fam = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    col_red = U.get("REDIKER ID") or U.get("REDIKERID") or U.get("REDIKER_ID") or U.get("REDIKER ID#")
    col_pf  = U.get("PARENT FIRST NAME") or U.get("PARENT FIRST") or U.get("FIRST PARENT NAME")
    col_pl  = U.get("PARENT LAST NAME")  or U.get("PARENT LAST")  or U.get("LAST PARENT NAME")
    col_sf  = U.get("CHILD FIRST NAME") or U.get("STUDENT FIRST NAME") or U.get("FIRST NAME") or U.get("FIRST")
    col_sl  = U.get("CHILD LAST NAME")  or U.get("STUDENT LAST NAME")  or U.get("LAST NAME")  or U.get("LAST")
    col_grade = U.get("GRADE") or U.get("GRADE LEVEL") or U.get("GR")
    if (not col_sf or not col_sl) and (U.get("STUDENT NAME") or U.get("CHILD NAME") or U.get("NAME")):
        name_col = U.get("STUDENT NAME") or U.get("CHILD NAME") or U.get("NAME")
        series = df[name_col].astype(str).str.strip()
        split = series.str.split(",", n=1, expand=True)
        if split.shape[1] != 2:
            split = series.str.split(";", n=1, expand=True)
        if split.shape[1] == 2:
            df["__Last"], df["__First"] = split[0].str.strip(), split[1].str.strip()
            col_sf, col_sl = "__First", "__Last"
    out = pd.DataFrame({
        "ID": df[col_id].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_id else "",
        "FAMILY ID": df[col_fam].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_fam else "",
        "PARENT FIRST NAME": df[col_pf].astype(str).str.strip() if col_pf else "",
        "PARENT LAST NAME":  df[col_pl].astype(str).str.strip() if col_pl else "",
        "STUDENT FIRST NAME": df[col_sf].astype(str).str.strip() if col_sf else "",
        "STUDENT LAST NAME":  df[col_sl].astype(str).str.strip() if col_sl else "",
        "GRADE": df[col_grade].astype(str).str.strip() if col_grade else "",
        "REDIKER ID": df[col_red].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if col_red else "",
        "SOURCE": "SR",
    })
    out["UNIQUE_KEY"] = [make_unique_key_lenient(f, l, g) for f, l, g in zip(out["STUDENT FIRST NAME"], out["STUDENT LAST NAME"], out["GRADE"])]
    return out

col1, col2, col3 = st.columns(3)
with col1:
    f_bb = st.file_uploader("Blackbaud (must contain 'Student name and grades')", type=["xlsx","xls"])
with col2:
    f_red = st.file_uploader("Rediker (header auto-detected)", type=["xlsx","xls"])
with col3:
    f_sr = st.file_uploader("Student Records", type=["xlsx","xls"])

run = st.button("Build Master Excel", type="primary", disabled=not (f_bb and f_red and f_sr))

if run:
    with st.spinner("Parsing & normalizing..."):
        try:
            bb_df  = parse_blackbaud(f_bb)
            red_df = parse_rediker(f_red)
            sr_df  = parse_student_records(f_sr)
        except Exception as e:
            st.error(f"Error while reading files: {e}")
            st.stop()

    TARGET_COLS = ["ID","FAMILY ID","PARENT FIRST NAME","PARENT LAST NAME",
                   "STUDENT FIRST NAME","STUDENT LAST NAME","GRADE","REDIKER ID","SOURCE"]
    for df in (bb_df, red_df, sr_df):
        for c in TARGET_COLS:
            if c not in df.columns:
                df[c] = ""
        df = df[TARGET_COLS]

    master = pd.concat([bb_df[TARGET_COLS], red_df[TARGET_COLS], sr_df[TARGET_COLS]], ignore_index=True)

    master["__SURNAME"] = master["STUDENT LAST NAME"].apply(surname_first_token)
    master["__FIRSTTOK"] = master.apply(lambda r: firstname_first_token(r["STUDENT FIRST NAME"], r["STUDENT LAST NAME"]), axis=1)
    master["__GRADELEN"] = master["GRADE"].apply(grade_norm)
    master["UNIQUE_KEY"] = master["__SURNAME"] + "|" + master["__FIRSTTOK"] + "|" + master["__GRADELEN"]
    master["__GROUP_KEY"] = master["__SURNAME"] + "|" + master["__GRADELEN"]
    src_counts = master.groupby("__GROUP_KEY")["SOURCE"].nunique().to_dict()
    master["__SRC_PRESENT"] = master["__GROUP_KEY"].map(src_counts).fillna(0).astype(int)

    source_order = {"BB":0, "RED":1, "SR":2}
    master["_source_rank"] = master["SOURCE"].map(lambda x: source_order.get(str(x).upper(), 99))
    master_sorted = master.sort_values(by=["UNIQUE_KEY","_source_rank","STUDENT LAST NAME","STUDENT FIRST NAME"], kind="mergesort").reset_index(drop=True)

    from collections import Counter
    summary_rows = []
    for gkey, grp in master.groupby("__GROUP_KEY"):
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

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
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
        for c_idx, col in enumerate(master_sorted.columns):
            ws1.write(0, c_idx, col, header_fmt)
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
        for helper in ["__SURNAME","__FIRSTTOK","__GRADELEN","__GROUP_KEY","__SRC_PRESENT","_source_rank"]:
            if helper in idx:
                ws1.set_column(idx[helper], idx[helper], None, None, {"hidden": True})

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
        label="⬇️ Download Master_Compare_with_Summary.xlsx",
        data=output.getvalue(),
        file_name="Master_Compare_with_Summary.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
# --------------------------------
# Footer: Build identifier & credit
# --------------------------------
import datetime
build_id = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
st.markdown(
    f"<hr><div style='text-align:center; font-size:0.9em; color:gray;'>"
    f"Build ID: <b>{build_id}</b> • Master Students Builder (lenient, debug version)"
    f"</div>",
    unsafe_allow_html=True,
)
