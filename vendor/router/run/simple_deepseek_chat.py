# aiohttp & related imports
import asyncio
import aiohttp

# local imports
import tools
import router


PROMPT = """
Как выбрать женскую рубашку по размеру и типу фигуры (кратко)
""".strip()


async def generate():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, PROMPT),
        }

        result = await router.llm.post(
            session,
            "external:deepseek-chat",
            payload,
        )

        print(tools.generate_json_preview(result))
        print("Total price:", result["stats"]["total_price"])
        print("Elapsed time:", result["elapsed_time"])


if __name__ == "__main__":
    asyncio.run(generate())