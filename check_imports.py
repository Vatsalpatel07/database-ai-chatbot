import ast
from pathlib import Path

ROOT = Path(".")

for file in sorted(ROOT.rglob("*.py")):

    # Ignore virtual environment and cache folders
    if any(
        part in {".venv", "venv", "__pycache__", ".git"}
        for part in file.parts
    ):
        continue

    print("\n" + "=" * 80)
    print(file)
    print("=" * 80)

    try:
        source = file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        print(f"ERROR: {e}")
        continue

    imports = set()

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)

    if imports:
        for module in sorted(imports):
            print(f"  -> {module}")
    else:
        print("  -> No imports")