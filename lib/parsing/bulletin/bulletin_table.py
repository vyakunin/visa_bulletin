"""
Data class for parsed visa bulletin tables.

Simple container: BulletinTable(title, headers, rows)
"""


class BulletinTable:
    def __init__(self, title, headers, rows):
        self.title = title
        self.headers = headers
        self.rows = rows

    def __repr__(self):
        return f"BulletinTable(title={self.title}, headers={self.headers}, rows={self.rows})"
