"""US state code constants and geographic location utilities

Note: Standard libraries like 'us' (pypi.org/project/us) were considered but deemed
unnecessary for our simple use case (just validating 2-letter codes). Our implementation
is lightweight and sufficient.
"""

# Valid US state codes (2-letter abbreviations)
VALID_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",  # District of Columbia
}

# US States for dropdown (code, name) tuples
US_STATES = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
]


def is_valid_state(state_code: str | None) -> bool:
    """
    Check if a state code is valid.

    Args:
        state_code: 2-letter state code to validate

    Returns:
        True if valid, False otherwise
    """
    if not state_code:
        return False
    return state_code.upper() in VALID_STATES


# Mapping from full state names to 2-letter codes (for normalization)
STATE_NAME_TO_CODE = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
}


# Geographic qualifiers that distinguish companies in employer names
# These words indicate geographic scope and should prevent matching different entities
# (e.g., "ROCA, INC." vs "Roca USA, Inc" are different companies)
GEOGRAPHIC_QUALIFIERS = {
    "usa",
    "us",
    "north",
    "south",
    "east",
    "west",
    "america",
    "americas",
}


def normalize_state_code(state: str | None) -> str:
    """
    Normalize state input to 2-letter code.

    Handles both full state names (e.g., "MASSACHUSETTS", "New York") and
    abbreviations (e.g., "MA", "NY"). Returns 2-letter code in uppercase.

    Args:
        state: State name or code (e.g., "MASSACHUSETTS", "MA", "New York", "ny")

    Returns:
        2-letter state code in uppercase, or original string (uppercased, first 2 chars)
        if not found in mapping. Returns empty string if input is None or empty.

    Examples:
        normalize_state_code("MASSACHUSETTS") -> "MA"
        normalize_state_code("MA") -> "MA"
        normalize_state_code("New York") -> "NY"
        normalize_state_code("ny") -> "NY"
        normalize_state_code("UNKNOWN") -> "UN" (fallback)
        normalize_state_code(None) -> ""
    """
    if not state:
        return ""

    state_upper = state.upper().strip()

    # Check if already a valid 2-letter code
    if state_upper in VALID_STATES:
        return state_upper

    # Check if it's a full state name
    if state_upper in STATE_NAME_TO_CODE:
        return STATE_NAME_TO_CODE[state_upper]

    # Fallback: return first 2 characters (uppercased)
    # This handles cases like "MASSACHUSETTS" -> "MA" (first 2 chars)
    # or unknown states -> first 2 chars
    return state_upper[:2] if len(state_upper) >= 2 else state_upper
