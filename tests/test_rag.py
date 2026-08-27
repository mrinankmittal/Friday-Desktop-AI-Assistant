from __future__ import annotations

import unittest

from friday.rag.chunk import chunk_text
from friday.rag.embed import cosine_similarity, embed_text
from friday.rag.extract import extract_text
from tests.helpers import make_memory_store


class ChunkAndEmbedTests(unittest.TestCase):
    def test_chunk_splits_long_text(self) -> None:
        text = "alpha " * 80
        chunks = chunk_text(text, size=40, overlap=8)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunks))

    def test_similar_text_scores_higher_than_unrelated(self) -> None:
        query = embed_text("vacation in Goa")
        match = embed_text("Goa vacation plans for December")
        other = embed_text("chrome window process list")
        self.assertGreater(cosine_similarity(query, match), cosine_similarity(query, other))

    def test_extract_text_file(self) -> None:
        folder, _store, root = make_memory_store()
        try:
            path = root / "note.txt"
            path.write_text("hello friday", encoding="utf-8")
            self.assertEqual(extract_text(path).strip(), "hello friday")
        finally:
            folder.cleanup()


if __name__ == "__main__":
    unittest.main()
