"""
Example: Backend agent that processes PDF slides page-by-page using Gemini.

This agent:
1. Uses Gemini's native PDF processing to analyze each page
2. Generates detailed descriptions of each slide
3. Stores the descriptions for later chunking and vector DB storage

This is designed for backend processing (not client-facing).
Uses Gemini's native PDF support - no image conversion needed!
"""

from pathlib import Path
from typing import List

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from pydantic import BaseModel, Field

try:
    from PyPDF2 import PdfReader
except ImportError:
    print("Please install PyPDF2: pip install PyPDF2")
    raise


class SlideContent(BaseModel):
    """Structured description of slide content"""

    page_number: int = Field(description="The page/slide number (1-indexed)")
    text_content: str = Field(
        description="All text content found on the slide, including headings, bullet points, and body text"
    )
    images_description: str = Field(
        description="Description of any images, photos, or illustrations on the slide"
    )
    diagrams_description: str = Field(
        description="Description of any diagrams, charts, graphs, flowcharts, or visual data representations"
    )
    figures_description: str = Field(
        description="Description of any figures, tables, or structured data visualizations"
    )
    overall_summary: str = Field(
        description="A concise summary of the slide's main topic and purpose"
    )
    slide_type: str = Field(
        description="Type of slide (e.g., 'title', 'content', 'diagram', 'comparison', 'summary')"
    )


class PDFSlideDescriptionAgent:
    """
    Backend agent for processing PDF slides and generating descriptions.
    
    This agent processes each page of a PDF directly using Gemini's native PDF support.
    No image conversion needed - Gemini handles PDFs natively!
    """

    def __init__(
        self,
        model_id: str = "gemini-2.0-flash-exp",
    ):
        """
        Initialize the PDF slide description agent.

        Args:
            model_id: Gemini model ID to use
        """
        self.agent = Agent(
            model=Gemini(id=model_id),
            output_schema=SlideContent,
            instructions="""
            You are an expert at analyzing presentation slides. Your task is to provide
            detailed, structured descriptions of slide content including:
            - All text content (headings, bullet points, body text)
            - Images and illustrations
            - Diagrams, charts, and graphs
            - Figures and tables
            - Overall summary and slide type
            
            Be thorough and accurate. If a category doesn't apply, indicate that clearly.
            When analyzing a specific page, focus only on that page's content.
            """,
            markdown=False,  # Backend processing, no need for markdown
        )

    def get_page_count(self, pdf_path: Path) -> int:
        """
        Get the number of pages in the PDF.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Number of pages
        """
        try:
            reader = PdfReader(pdf_path)
            return len(reader.pages)
        except Exception as e:
            raise RuntimeError(f"Failed to read PDF: {e}")

    def process_pdf(
        self, pdf_path: Path
    ) -> List[SlideContent]:
        """
        Process a PDF file page by page and generate descriptions.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of SlideContent objects, one per page
        """
        print(f"Processing PDF: {pdf_path}")

        # Get page count
        page_count = self.get_page_count(pdf_path)
        print(f"Found {page_count} pages")

        # Process each page
        descriptions = []
        pdf_file = File(filepath=pdf_path)

        for page_num in range(1, page_count + 1):
            print(f"\nProcessing page {page_num}/{page_count}...")

            # Generate description using Gemini
            # Gemini can process PDFs directly and we can ask it to focus on specific pages
            prompt = f"""
            Analyze page {page_num} of this PDF presentation slide.
            Provide a detailed description including:
            - All text content (headings, bullet points, body text)
            - Any images, photos, or illustrations
            - Any diagrams, charts, graphs, or flowcharts
            - Any figures, tables, or structured data
            - A summary of the slide's main topic
            - The type of slide (title, content, diagram, comparison, summary, etc.)
            
            Focus ONLY on page {page_num}. Do not describe other pages.
            """

            response = self.agent.run(
                input=prompt,
                files=[pdf_file],
            )

            # Extract structured output
            if hasattr(response, "content") and isinstance(
                response.content, SlideContent
            ):
                slide_content = response.content
                # Ensure page number is set correctly
                slide_content.page_number = page_num
            else:
                # Fallback: try to parse if content is dict
                try:
                    if isinstance(response.content, dict):
                        response.content["page_number"] = page_num
                        slide_content = SlideContent(**response.content)
                    else:
                        slide_content = SlideContent(
                            page_number=page_num,
                            text_content=str(response.content),
                            images_description="Unable to extract",
                            diagrams_description="Unable to extract",
                            figures_description="Unable to extract",
                            overall_summary="Unable to extract",
                            slide_type="unknown",
                        )
                except Exception:
                    # Last resort: create from text response
                    slide_content = SlideContent(
                        page_number=page_num,
                        text_content=str(response.content),
                        images_description="Unable to extract",
                        diagrams_description="Unable to extract",
                        figures_description="Unable to extract",
                        overall_summary="Unable to extract",
                        slide_type="unknown",
                    )

            descriptions.append(slide_content)
            print(f"✓ Page {page_num} processed: {slide_content.overall_summary[:100]}...")

        return descriptions

    def save_descriptions(
        self, descriptions: List[SlideContent], output_path: Path
    ) -> None:
        """
        Save descriptions to a JSON file for later processing.

        Args:
            descriptions: List of slide descriptions
            output_path: Path to save JSON file
        """
        import json

        # Convert to dict for JSON serialization
        data = [desc.model_dump() for desc in descriptions]

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\nSaved {len(descriptions)} descriptions to {output_path}")


def main():
    """
    Example usage of the PDF slide description agent.
    """
    # Initialize the agent
    agent = PDFSlideDescriptionAgent(
        model_id="gemini-2.0-flash-exp",  # or "gemini-2.5-pro" for better quality
    )

    # Path to your PDF file
    pdf_path = Path(__file__).parent / "sample_slides.pdf"

    # Process the PDF
    try:
        descriptions = agent.process_pdf(pdf_path=pdf_path)

        # Save descriptions to JSON
        descriptions_path = Path(__file__).parent / "slide_descriptions.json"
        agent.save_descriptions(descriptions, descriptions_path)

        # Print summary
        print("\n" + "=" * 60)
        print("PROCESSING COMPLETE")
        print("=" * 60)
        print(f"Total pages processed: {len(descriptions)}")
        print("\nSample descriptions:")
        for desc in descriptions[:3]:  # Show first 3
            print(f"\nPage {desc.page_number}:")
            print(f"  Type: {desc.slide_type}")
            print(f"  Summary: {desc.overall_summary}")
            print(f"  Text: {desc.text_content[:100]}...")

        print("\nNext steps:")
        print("1. Review slide_descriptions.json")
        print("2. Chunk the descriptions using your chunking strategy")
        print("3. Store chunks in your vector database")

    except FileNotFoundError:
        print(f"PDF file not found: {pdf_path}")
        print("Please provide a PDF file to process.")
    except Exception as e:
        print(f"Error processing PDF: {e}")
        raise


if __name__ == "__main__":
    main()