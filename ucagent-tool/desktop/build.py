"""Build a portable standard-library zipapp without packaging caches or backend dependencies."""

from pathlib import Path
import shutil
import tempfile
import zipapp


def main():
    """Copy only desktop package source/resources into an isolated staging directory."""
    source = Path(__file__).resolve().parent
    output = source / "dist" / "UCAgent-Desktop.pyz"
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ucagent-desktop-build-") as directory:
        target = Path(directory) / "ucagent_tk"
        shutil.copytree(str(source / "ucagent_tk"), str(target), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(str(source / "ucagent_app.py"), str(Path(directory) / "__main__.py"))
        zipapp.create_archive(directory, target=str(output), compressed=True)
    print(output)


if __name__ == "__main__":
    main()
