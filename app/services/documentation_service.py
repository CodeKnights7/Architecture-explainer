from app.core.markdown_generator import MarkdownGenerator
from app.core.json_generator import JSONGenerator


class DocumentationService:

    @staticmethod
    async def generate_documentation(ai_response: str):

        markdown_doc = MarkdownGenerator.generate(
            ai_response
        )

        json_doc = JSONGenerator.generate(
            ai_response
        )

        return {
            "markdown": markdown_doc,
            "json": json_doc
        }