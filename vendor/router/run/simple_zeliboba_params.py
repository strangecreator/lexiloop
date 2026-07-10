# aiohttp & related imports
import asyncio
import aiohttp

# local imports
import router


async def generate():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Create a weekly study plan for: probability, linear algebra, algorithms (10 hours/week)."),
            "temperature": 0.5,
            "top_p": 0.9,
            "min_tokens": 0,
            "max_tokens": 10_000,
            "mode": "StochasticBeamSearch",
        }

        result = await router.llm.post(
            session,
            "internal:zeliboba-32b_aligned_quantized_202506_reasoner",
            payload,
        )

        print(result["reasoning_content"], end='-' * 30)
        print(result["content"])


if __name__ == "__main__":
    asyncio.run(generate())