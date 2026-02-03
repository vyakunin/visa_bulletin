"""
Enforce no __init__.py in designated code directories.

The test depends on //lib/business/salary:no_init_check genrule.
That genrule fails the build if __init__.py exists in that directory,
so if the test runs, the check already passed. See .cursor/rules/general_code_health.mdc
"No __init__.py in Designated Code Directories".
"""


def test_no_init_in_code_dirs():
    """Placeholder; real enforcement is genrule no_init_check (fails build if __init__.py added)."""
    pass
