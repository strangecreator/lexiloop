import pathlib

BASE_DIR = pathlib.Path(__file__).parents[1]
RESOURCES_DIR = BASE_DIR / "resources"

# local imports
import tools
import router


if __name__ == "__main__":
    result = router.get_all_eliza_models()

    (RESOURCES_DIR / "run/all_eliza_models.json").write_text(tools.generate_json_preview(result), encoding="utf-8")
