# aiohttp & related imports
import asyncio
import aiohttp

# local imports
import tools
import router


async def generate():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Create a weekly study plan for: probability, linear algebra, algorithms (10 hours/week)."),
        }

        result = await router.llm.post(
            session,
            "internal:gpt-5.2",
            payload,
            reasoning_effort="high",
        )

        print(tools.generate_json_preview(result))
        print("Total price:", result["stats"]["total_price"])


if __name__ == "__main__":
    asyncio.run(generate())