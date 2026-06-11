import sys


class Document:
    def __init__(self, page_content: str = "", metadata: dict = None):
        self.page_content = page_content
        self.metadata = metadata or {}


from langchain_text_splitters import RecursiveCharacterTextSplitter


class _DocstoreModule:
    class document:
        Document = Document


class _TextSplitterModule:
    RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter


sys.modules["langchain.docstore"] = _DocstoreModule()
sys.modules["langchain.docstore.document"] = _DocstoreModule.document
sys.modules["langchain.text_splitter"] = _TextSplitterModule()
