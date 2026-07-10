# aiohttp & related imports
import asyncio
import aiohttp

# local imports
import tools
import router


async def generate():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Напиши стихотворение какое-нибудь красивое, но придумай новое"),
        }

        result = await router.llm.post(
            session,
            # "internal:deepseek-reasoner",
            "external:deepseek-reasoner",
            payload,
        )

        print(tools.generate_json_preview(result))
        print("Total price:", result["stats"]["total_price"])


if __name__ == "__main__":
    asyncio.run(generate())