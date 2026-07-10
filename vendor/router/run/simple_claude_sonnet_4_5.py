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
            "internal:claude-sonnet-4-5",
            payload,
            max_tokens=2048,
            temperature=1,  # temperature can only be set to 1, when thinking is enabled
            thinking={
                "type": "enabled",
                "budget_tokens": 1024,
                "display": "summarized",
            },
        )

        print(tools.generate_json_preview(result))
        print("Total price:", result["stats"]["total_price"])


if __name__ == "__main__":
    asyncio.run(generate())