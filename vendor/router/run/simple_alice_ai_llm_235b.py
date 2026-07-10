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
        }

        result = await router.llm.post(
            session,
            "internal:alice-ai-llm-235b",
            payload,
        )

        print(result["reasoning_content"], end='-' * 30)
        print(result["content"])


if __name__ == "__main__":
    asyncio.run(generate())