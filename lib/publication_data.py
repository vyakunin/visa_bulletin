class PublicationData:
    def __init__(self, url, content, publication_date):
        self.url = url
        self.content = content
        self.publication_date = publication_date

    def __repr__(self):
        return f"PublicationData(url={self.url}, content_length={len(self.content)}, publication_date={self.publication_date})"