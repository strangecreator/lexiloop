from tools.archive_utils import archive_selected, resolve_selected_dirs


root = "/Users/dark-creator/solomon/yandex/packages/tools"


archive_path = archive_selected(root, [
    "src",
    "run",
    "tests",
    ".gitignore",
    "pyproject.toml",
    "README.md",
])

print(archive_path)