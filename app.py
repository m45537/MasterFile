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
