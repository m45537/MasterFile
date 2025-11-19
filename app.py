def parse_rediker(file) -> pd.DataFrame:
    """
    Rediker export where:
      - STUDENT NAME = student full name
      - FIRST NAME / LAST NAME = parent names
      - APID (or UNIQUE ID) = student ID
    """
    # Detect header row in first ~12 lines, just to be robust
    probe = pd.read_excel(file, header=None, nrows=12)
    tokens = {"APID","STUDENT","STUDENT NAME","FIRST","LAST","GRADE","UNIQUE"}
    best_row, best_hits = 0, -1
    for i in range(len(probe)):
        row = " ".join(str(x).upper() for x in probe.iloc[i].tolist())
        hits = sum(tok in row for tok in tokens)
        if hits > best_hits:
            best_row, best_hits = i, hits

    df = pd.read_excel(file, header=best_row).fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    U = {c.upper(): c for c in df.columns}

    # Student name column (must exist)
    student_col = (
        U.get("STUDENT NAME")
        or U.get("STUDENT")
        or U.get("STUDENT_NAME")
    )
    if not student_col:
        st.error("Rediker: couldn’t find STUDENT NAME column. Please check the export.")
        st.stop()

    # Parent name columns (optional but we expect them)
    parent_first_col = U.get("FIRST NAME") or U.get("FIRST")
    parent_last_col  = U.get("LAST NAME")  or U.get("LAST")

    # Grade column (we still keep tolerant detection)
    grade_keys = (
        "GRADE","GRADE LEVEL","GRADELEVEL","GR","GR LEVEL","GRLEVEL",
        "GRADE_LVL","CURRENT GRADE","CUR GRADE","LVL"
    )
    grade_col = None
    for k, orig in U.items():
        kk = " ".join(k.split())
        if kk in grade_keys or ( "GRADE" in kk and "FAMILY" not in kk ):
            grade_col = orig
            break

    # If missing, we’ll still allow blanks and warn
    inferred_grade = None
    if not grade_col:
        st.warning("Rediker: no GRADE column found. Proceeding with blanks.")
    # If your file always has GRADE, this branch won’t be used.

    # Family ID (if present) and Rediker ID
    fam_col = U.get("FAMILY ID") or U.get("FAMILYID") or U.get("FAMILY_ID")
    rid_col = U.get("APID") or U.get("UNIQUE ID") or U.get("UNIQUEID") or U.get("ID")

    def split_student_name(val: str):
        if pd.isna(val) or str(val).strip() == "":
            return "", ""
        s = str(val).strip()
        # Common Rediker patterns: "RIVERA; ALEXANDER", "RIVERA, ALEXANDER", "ALEXANDER RIVERA"
        if ";" in s:
            last, first = [t.strip() for t in s.split(";", 1)]
        elif "," in s:
            last, first = [t.strip() for t in s.split(",", 1)]
        else:
            parts = s.split()
            if len(parts) >= 2:
                # Assume "FIRST LAST" style if space-separated
                first = " ".join(parts[:-1])
                last  = parts[-1]
            elif len(parts) == 1:
                first, last = parts[0], ""
            else:
                first, last = "", ""
        return first, last

    rows = []
    for idx, r in df.iterrows():
        stud_first, stud_last = split_student_name(r.get(student_col, ""))

        parent_first = str(r.get(parent_first_col, "")).strip() if parent_first_col else ""
        parent_last  = str(r.get(parent_last_col,  "")).strip() if parent_last_col  else ""

        if grade_col:
            grade = str(r.get(grade_col, "")).strip()
        else:
            grade = ""  # no inference in this simplified version

        fam = str(r.get(fam_col, "")).replace(".0","").strip() if fam_col else ""
        rid = str(r.get(rid_col, "")).replace(".0","").strip() if rid_col else ""

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

