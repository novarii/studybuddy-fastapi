"""
Custom chunking strategy for PDF slide descriptions.

This strategy:
- Chunks by slide (one chunk per slide by default)
- If a slide is too large, splits it into 2 chunks
- Preserves slide metadata and context
"""

from typing import Dict, List, Optional

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


class SlideChunking(ChunkingStrategy):
    """
    Custom chunking strategy for slide descriptions.
    
    Chunks by slide, but splits large slides into 2 chunks if they exceed max_chars.
    """

    def __init__(self, max_chars: int = 2000, **kwargs):
        """
        Initialize slide chunking strategy.

        Args:
            max_chars: Maximum characters per chunk. If slide exceeds this, split into 2 chunks.
            **kwargs: Additional parameters
        """
        self.max_chars = max_chars
        super().__init__(**kwargs)

    def chunk(self, document: Document) -> List[Document]:
        """
        Chunk a slide document.

        Args:
            document: Document containing slide description

        Returns:
            List of chunked Documents (1 or 2 chunks per slide)
        """
        content = self.clean_text(document.content)
        
        if not content:
            return []

        # If content is small enough, return as single chunk
        if len(content) <= self.max_chars:
            meta = dict(document.meta_data or {})
            meta.update({
                "chunk": 1,
                "total_chunks": 1,
                "chunking_strategy": "slide_chunking",
            })
            return [
                Document(
                    id=document.id,
                    name=document.name,
                    meta_data=meta,
                    content=content,
                )
            ]

        # Otherwise, split into 2 chunks
        # Split at approximately the middle, but try to split at a sentence boundary
        mid_point = len(content) // 2
        
        # Try to find a good split point (sentence boundary)
        split_point = self._find_split_point(content, mid_point)
        
        # Create two chunks
        chunk1_content = content[:split_point].strip()
        chunk2_content = content[split_point:].strip()

        chunks = []
        
        # First chunk
        if chunk1_content:
            meta_data_1 = dict(document.meta_data or {})
            meta_data_1["chunk"] = 1
            meta_data_1["total_chunks"] = 2
            meta_data_1["chunking_strategy"] = "slide_chunking"
            
            chunks.append(
                Document(
                    id=f"{document.id}_chunk_1" if document.id else None,
                    name=f"{document.name} (Part 1/2)",
                    meta_data=meta_data_1,
                    content=chunk1_content,
                )
            )

        # Second chunk
        if chunk2_content:
            meta_data_2 = dict(document.meta_data or {})
            meta_data_2["chunk"] = 2
            meta_data_2["total_chunks"] = 2
            meta_data_2["chunking_strategy"] = "slide_chunking"
            
            chunks.append(
                Document(
                    id=f"{document.id}_chunk_2" if document.id else None,
                    name=f"{document.name} (Part 2/2)",
                    meta_data=meta_data_2,
                    content=chunk2_content,
                )
            )

        return chunks if chunks else [document]

    def _find_split_point(self, text: str, preferred_point: int) -> int:
        """
        Find a good split point near the preferred point.
        Tries to split at sentence boundaries (., !, ?) or paragraph breaks.

        Args:
            text: Text to split
            preferred_point: Preferred split point

        Returns:
            Actual split point
        """
        # Look for sentence endings near the preferred point
        # Search within 200 characters of preferred point
        search_range = 200
        start = max(0, preferred_point - search_range)
        end = min(len(text), preferred_point + search_range)

        search_text = text[start:end]
        
        # Try to find sentence endings
        for delimiter in [".\n", ".\n\n", "!\n", "?\n", ".\n", "! ", "? ", ". "]:
            # Look backwards from preferred point
            pos = search_text.rfind(delimiter, 0, preferred_point - start)
            if pos != -1:
                return start + pos + len(delimiter)
            
            # Look forwards from preferred point
            pos = search_text.find(delimiter, preferred_point - start)
            if pos != -1:
                return start + pos + len(delimiter)

        # If no good split point found, use preferred point
        return preferred_point


# Example usage function
def chunk_slide_descriptions(
    descriptions: List[dict],
    document_id: str,
    max_chars: int = 2000,
    extra_meta: Optional[Dict] = None,
) -> List[Document]:
    """
    Convert slide descriptions to chunked Documents.

    Args:
        descriptions: List of slide description dicts (from API response)
        document_id: Document ID for the PDF
        max_chars: Maximum characters per chunk

    Returns:
        List of chunked Documents ready for vector DB
    """
    from agno.knowledge.document.base import Document

    chunking_strategy = SlideChunking(max_chars=max_chars)
    all_chunks = []

    for desc in descriptions:
        # Build content from description
        content_parts = [
            f"Page {desc['page_number']}",
            f"Slide Type: {desc['slide_type']}",
            f"Summary: {desc['overall_summary']}",
            "",
            "Text Content:",
            desc.get("text_content", ""),
            "",
            "Images:",
            desc.get("images_description", ""),
            "",
            "Diagrams:",
            desc.get("diagrams_description", ""),
            "",
            "Figures:",
            desc.get("figures_description", ""),
        ]

        content = "\n".join(content_parts)

        # Create document
        meta = {
            "document_id": document_id,
            "page_number": desc["page_number"],
            "slide_type": desc.get("slide_type", "unknown"),
            "summary": desc.get("overall_summary", ""),
        }
        if extra_meta:
            meta.update(extra_meta)

        doc = Document(
            id=f"{document_id}_page_{desc['page_number']}",
            name=f"Slide {desc['page_number']}",
            content=content,
            meta_data=meta,
        )

        # Chunk the document
        chunks = chunking_strategy.chunk(doc)
        all_chunks.extend(chunks)

    return all_chunks
