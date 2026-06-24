import os
import time
import psutil


class Metrics:

    @staticmethod
    def get_cpu_percent():

        return round(
            psutil.cpu_percent(
                interval=0.1
            ),
            2
        )

    @staticmethod
    def get_memory_usage_mb():

        process = psutil.Process(
            os.getpid()
        )

        memory_mb = (
            process.memory_info().rss
            / 1024
            / 1024
        )

        return round(
            memory_mb,
            2
        )

    @staticmethod
    def get_system_memory_percent():

        return round(
            psutil.virtual_memory().percent,
            2
        )

    @staticmethod
    def get_available_memory_mb():

        available = (
            psutil.virtual_memory()
            .available
            / 1024
            / 1024
        )

        return round(
            available,
            2
        )

    @staticmethod
    def start_timer():

        return time.perf_counter()

    @staticmethod
    def stop_timer(
        start_time
    ):

        return round(
            (
                time.perf_counter()
                - start_time
            )
            * 1000,
            2
        )

    @staticmethod
    def get_metrics_snapshot():

        return {

            "cpu_percent":
            Metrics.get_cpu_percent(),

            "memory_usage_mb":
            Metrics.get_memory_usage_mb(),

            "system_memory_percent":
            Metrics.get_system_memory_percent(),

            "available_memory_mb":
            Metrics.get_available_memory_mb()
        }