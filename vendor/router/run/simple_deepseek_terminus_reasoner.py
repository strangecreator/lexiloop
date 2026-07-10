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
            "max_tokens": 1000,
        }

        result = await router.llm.post(
            session,
            "internal:deepseek-v3.1-terminus-batch-reasoner",
            payload,
        )

        print(result["content"], end="\n\n\n")
        print(result["reasoning_content"])


if __name__ == "__main__":
    asyncio.run(generate())