import re

from setuptools import setup


version = ""
with open("postgreslite/__init__.py") as f:
    version = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', f.read(), re.MULTILINE).group(1)


setup(
    name="postgreslite",
    author="AlexFlipnote",
    version=version,
    packages=["postgreslite"],
    description="Python SQLite combined with syntax compared to asyncpg progject.",
    include_package_data=True
)
