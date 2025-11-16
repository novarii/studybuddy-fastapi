import pytest
from agno.knowledge.document.base import Document

from app.chunkings.chunking import TimestampAwareChunking
from app.chunkings.slide_chunking import SlideChunking, chunk_slide_descriptions


def build_doc(segments=None, content="Hello world"):
    meta = {}
    if segments is not None:
        meta["segments"] = segments
    return Document(
        id="lecture_1",
        name="Concurrency 101",
        content=content,
        meta_data=meta,
    )


def test_timestamp_chunker_preserves_start_end():
    segments = [
        {"text": "Good", "start_ms": 0, "end_ms": 500},
        {"text": "morning", "start_ms": 500, "end_ms": 1100},
        {"text": "everyone", "start_ms": 1100, "end_ms": 1900},
        {"text": "today", "start_ms": 1900, "end_ms": 2600},
    ]
    doc = build_doc(segments=segments)
    chunker = TimestampAwareChunking(max_words=2, max_duration_ms=2_000, overlap_ms=400)

    chunks = chunker.chunk(doc)

    assert len(chunks) == 4
    assert chunks[0].meta_data["start_ms"] == 0
    assert chunks[0].meta_data["end_ms"] == 1100
    assert "Good morning" in chunks[0].content

    assert chunks[1].meta_data["start_ms"] == 500  # overlap preserves previous tail
    assert chunks[1].meta_data["end_ms"] == 1900
    assert "morning everyone" in chunks[1].content

    assert chunks[2].meta_data["start_ms"] == 1100  # overlap from previous chunk
    assert chunks[2].meta_data["end_ms"] == 2600
    assert "everyone today" in chunks[2].content

    assert chunks[3].meta_data["start_ms"] == 1900  # final buffer flush
    assert chunks[3].meta_data["end_ms"] == 2600
    assert "today" in chunks[3].content


def test_timestamp_chunker_fallback_without_segments():
    doc = build_doc(segments=None, content="One two three four five six")
    chunker = TimestampAwareChunking(max_words=2, overlap_ms=0)

    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    assert chunks[0].meta_data["chunking_strategy"] == "timestamp_aware_fallback"
    assert chunks[0].content == "One two"


def test_slide_chunking_handles_short_and_long_slides():
    slide_descriptions = [
        {
            "page_number": 1,
            "text_content": "(Simplified) x86 Processor State\nRF: Program registers\nCC: Condition codes\nStat: Program status\n%rax %rsp %r8 %r12\n%rcx %rbp %r9 %r13\nZF SF OF\nDMEM: Memory\n%rdx %rsi %r10 %r14\nPC\n%rbx %rdi %r11\n• Processor state is what's visible to assembly programs. Also known as architecture state.\n• Program Registers: 15 registers.\n• Condition Codes: Single-bit flags set by arithmetic or logical instructions (ZF, SF, OF)\n• Program Counter: Indicates address of next instruction\n• Program Status: Indicates either normal operation or error condition\n• Memory\n• Byte-addressable storage array\n• Words stored in little-endian byte order\n12",
            "images_description": "There are no images or photos on this slide. It contains a diagram representing the x86 processor state.",
            "diagrams_description": "The slide contains a diagram representing the simplified x86 processor state. The diagram has several components:\n\n1.  **Program Registers (RF)**: A table listing registers %rax, %rsp, %r8, %r12, %rcx, %rbp, %r9, %r13, %rdx, %rsi, %r10, %r14, %rbx, %rdi, and %r11.\n2.  **Condition Codes (CC)**: Shows ZF, SF, and OF flags.\n3.  **Program Status (Stat)**: Shows DMEM (Memory) and PC (Program Counter).",
            "figures_description": "The slide contains tabular data outlining the registers and condition codes within the x86 processor state.  It details register names and flags.",
            "overall_summary": "This slide describes the simplified x86 processor state, covering program registers, condition codes, program counter, program status, and memory.",
            "slide_type": "content",
        },
        {
            "page_number": 2,
            "text_content": "Why Have Instructions?\n\n•\tWhy do we need an ISA? Can we directly program the hardware?\n•\tSimplifies interface\n•\tSoftware knows what is available\n•\tHardware knows what needs to be implemented\n•\tAbstraction protects software and hardware\n•\tSoftware can run on new machines\n•\tHardware can run old software\n•\tAlternatives: Application-Specific Integrated Circuits (ASIC)\n•\tNo instructions, (largely) not programmable, fixed-functioned, so no instruction fetch, decoding, etc.\n•\tSo could be implemented extremely efficiently.\n•\tExamples: video/audio codec, (conventional) image signal processors, (conventional) IP packet router",
            "images_description": "There are no images on this slide.",
            "diagrams_description": "There are no diagrams on this slide.",
            "figures_description": "There are no figures on this slide.",
            "overall_summary": "This slide discusses the need for instructions and ISAs (Instruction Set Architectures) in programming. It highlights the advantages of using instructions, such as simplified interfaces, software/hardware protection through abstraction, and provides alternatives such as ASICs.",
            "slide_type": "content",
        },
    ]

    document_id = "doc_20251115_222208_234641"
    chunking_strategy = SlideChunking(max_chars=800)

    chunks = chunk_slide_descriptions(slide_descriptions, document_id, max_chars=800)

    assert len(chunks) >= 2
    first_page_chunks = [c for c in chunks if c.meta_data["page_number"] == 1]
    second_page_chunks = [c for c in chunks if c.meta_data["page_number"] == 2]

    assert len(first_page_chunks) >= 1
    assert first_page_chunks[0].meta_data["chunking_strategy"] == "slide_chunking"
    assert first_page_chunks[0].meta_data["document_id"] == document_id

    # Second page content (with all description fields combined) exceeds max_chars, so it gets split
    assert len(second_page_chunks) == 2
    assert second_page_chunks[0].meta_data["chunk"] == 1
    assert second_page_chunks[1].meta_data["chunk"] == 2
    assert "Why Have Instructions" in second_page_chunks[0].content
