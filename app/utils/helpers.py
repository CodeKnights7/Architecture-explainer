import os
from datetime import datetime


class Helpers:

    @staticmethod
    def get_file_size(file_path: str):
        size = os.path.getsize(file_path)

        return round(size / (1024 * 1024), 2)

    @staticmethod
    def generate_timestamp():
        return datetime.utcnow().isoformat()

    @staticmethod
    def clean_text(text: str):
        return " ".join(text.split())

    @staticmethod
    def format_response(data):
        return {
            "success": True,
            "timestamp": Helpers.generate_timestamp(),
            "data": data
        }