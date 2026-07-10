# aiohttp & related imports
import asyncio
import aiohttp

# local imports
import tools
import router


async def generate():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "What time is it in Moscow?"),
            # "temperature": 0.5,
            # "top_p": 0.9,
            # "min_tokens": 0,
            # "max_tokens": 1000,
            # "effor": "high",
            # "reasoning": {"enabled": True, "effort": "high"},
        }

        result = await router.llm.post(
            session=session,
            model="internal:openrouter-gpt-5.2",
            payload=payload,

            pool="ads",
            reasoning={"enabled": True, "effort": "high"},
        )

        print(tools.generate_json_preview(result))
        print("Total price:", result["stats"]["total_price"])


if __name__ == "__main__":
    asyncio.run(generate())