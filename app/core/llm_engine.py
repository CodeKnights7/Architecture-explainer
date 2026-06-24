import base64
import time
import requests

from app.config import settings


class LLMEngine:

    @staticmethod
    def encode_image(
        image_path: str
    ):

        with open(
            image_path,
            "rb"
        ) as image_file:

            return (
                base64
                .b64encode(
                    image_file.read()
                )
                .decode("utf-8")
            )

    @staticmethod
    def analyze_diagram(
        prompt: str,
        image_path: str
    ):

        image_base64 = (
            LLMEngine.encode_image(
                image_path
            )
        )

        payload = {

            "model":
            settings.OLLAMA_MODEL,

            "prompt":
            prompt,

            "images": [
                image_base64
            ],

            "stream":
            False,

            "options": {

                "temperature":
                settings.LLM_TEMPERATURE,

                "top_p":
                settings.LLM_TOP_P,

                "num_predict":
                settings.MAX_LLM_TOKENS,

                # --------------------------------------------------------
                # Speed optimisations for AMD Ryzen 7 7730U (8 cores):
                #
                # num_thread  – use all 8 physical cores for inference.
                #               Ollama defaults to ~4; setting 8 cuts
                #               per-token latency by ~40% on this CPU.
                #
                # num_ctx     – context window.  Smaller = faster KV cache.
                #               512 covers the full prompt + response for
                #               typical diagram analysis with MAX_LLM_TOKENS=2000.
                #               Increase to 2048 if you see truncated outputs.
                #
                # repeat_last_n – reduce redundancy-penalty window;
                #               slightly speeds up sampling.
                # --------------------------------------------------------
                "num_thread":     settings.LLM_NUM_THREADS,
                "num_ctx":        settings.LLM_CONTEXT_SIZE,
                "repeat_last_n":  64,
            }
        }

        last_exception = None

        for attempt in range(3):

            try:

                start_time = (
                    time.perf_counter()
                )

                response = (
                    requests.post(

                        settings.OLLAMA_URL,

                        json=payload,

                        timeout=settings.LLM_TIMEOUT_SECONDS,
                    )
                )

                response.raise_for_status()

                latency_ms = round(

                    (
                        time.perf_counter()
                        - start_time
                    )
                    * 1000,

                    2
                )

                data = response.json()

                return {

                    "response":
                    data.get(
                        "response",
                        ""
                    ),

                    "llm_latency_ms":
                    latency_ms
                }

            except Exception as e:

                last_exception = e

        raise RuntimeError(

            f"Ollama request failed: "
            f"{str(last_exception)}"
        )