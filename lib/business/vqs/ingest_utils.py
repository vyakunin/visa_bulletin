"""Shared utilities for VQS data ingestion"""

from datetime import date, datetime

from models.enums.country import Country


def parse_date_str(d_str: str) -> date | None:
    if not d_str:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    return None


def normalize_country(c_str: str) -> int:
    return Country.from_header(c_str) or Country.ALL


def normalize_month(m_str: str) -> int:
    try:
        if m_str.isdigit():
            return int(m_str)
        # Try full name or abbr
        import calendar

        m_map = {name: i for i, name in enumerate(calendar.month_name) if name}
        if m_str in m_map:
            return m_map[m_str]
        m_map_abbr = {name: i for i, name in enumerate(calendar.month_abbr) if name}
        if m_str in m_map_abbr:
            return m_map_abbr[m_str]
    except (ValueError, TypeError):
        pass
    return 0


def normalize_visa_class_inventory(v_str: str) -> str:
    # Logic from ingest_i485_inventory.py
    v = v_str.upper().strip()
    if "1ST" in v or "E1" in v:
        return "1st"
    if "2ND" in v or "E2" in v:
        return "2nd"
    if "3RD" in v or "E3" in v:
        return "3rd"
    if "4TH" in v:
        return "4th"
    if "5TH" in v:
        return "5th"
    return "Unknown"


def normalize_visa_class_perm(row: dict, extra_mappings: dict) -> str:
    # Logic from ingest_perm_disclosure.py / dol_perm_supply.py
    from lib.parsing.salary.db_importer import get_column_value

    edu = get_column_value(row, extra_mappings["education"]) or ""
    if not edu:
        return "3rd"

    edu_upper = str(edu).upper()
    if "MASTER" in edu_upper or "DOCTORATE" in edu_upper or "PROFESSIONAL" in edu_upper:
        return "2nd"
    if "BACHELOR" in edu_upper:
        try:
            exp_months = int(
                float(get_column_value(row, extra_mappings["experience_months"]) or 0)
            )
            if exp_months >= 60:
                return "2nd"
        except (ValueError, TypeError):
            pass
        return "3rd"

    if "NONE" in edu_upper or "HIGH SCHOOL" in edu_upper:
        return "3rd"

    return "3rd"
