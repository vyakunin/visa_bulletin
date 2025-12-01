class Table:
    def __init__(self, title, headers, rows):
        self.title = title
        self.headers = headers
        self.rows = rows

    def __repr__(self):
        return f"Table(title={self.title}, headers={self.headers}, rows={self.rows})"