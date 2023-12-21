import tempfile
import textwrap
import os
import json
import pytest

from tools import load, save, run


@pytest.fixture(autouse=True)
def create_conan_home():
    old_env = dict(os.environ)
    env_vars = {"CONAN_HOME": tempfile.mkdtemp(suffix='conans')}
    os.environ.update(env_vars)
    current = tempfile.mkdtemp(suffix="conans")
    cwd = os.getcwd()
    os.chdir(current)
    os.mkdir("all")
    try:
        yield
    finally:
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(old_env)


@pytest.fixture(autouse=True)
def generate_config_conandata():
    config_yml = textwrap.dedent("""
            versions:
              "0.1.0":
                folder: "all"
            """)
    save("config.yml", config_yml)
    conandata_yml = textwrap.dedent("""
            sources:
              "0.1.0":
                sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                url: "http://foobar.com/downloads/0.1.0.tar.gz"
            """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)

    run("git init")
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add version 0.1.0'")


@pytest.fixture(autouse=True)
def install_conan_config():
    repo = os.path.join(os.path.dirname(__file__), "..")
    run(f"conan config install {repo}")


def _save_config_conandata(pkg_version):
    config_yml = textwrap.dedent(f"""
            versions:
              "0.1.0":
                folder: "all"
              "{pkg_version}":
                folder: "all"
            """)
    conandata_yml = textwrap.dedent(f"""
            sources:
              "0.1.0":
                sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                url: "http://foobar.com/downloads/0.1.0.tar.gz"
              "{pkg_version}":
                sha256: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                url: "http://foobar.com/downloads/0.1.1.tar.gz"
            """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)


@pytest.mark.parametrize("version, expected_bump_version", [
    ("0.1.1", ["0.1.1"]),
    ("0.2", ["0.2"]),
    ("0.1.3.4", []),
    ("cci.20231207", []),
    ("v0.1.2", []),
    ("0.1.1-rc", []),
    ("0.1.1-beta", []),
])
def test_config_yml_add_version(version, expected_bump_version):
    """
    Only semver (without pre-release) and major.minor version should be classified as bump version
    """
    _save_config_conandata(version)

    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add version {version}'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": expected_bump_version, "bump_requirements": [], "bump_tools_requirements": [], "bump_test_requirements": []}


def test_add_conanfile():
    """
    Only when changing config.yml and conandata.yml should be classified as bump version
    """
    _save_config_conandata("0.1.1")
    conanfile = textwrap.dedent(f"""
                from conan import ConanFile
                class foo(ConanFile):
                    pass
                """)
    save("all/conanfile.py", conanfile)
    run("git add config.yml all/conandata.yml all/conanfile.py")
    run("git commit -m 'Add package'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


def test_add_extra_entry_in_config_root():
    """
    Only versions should be changed in config.yml to be classified as bump version
    """
    config_yml = textwrap.dedent(f"""
                versions:
                  "0.1.0":
                    folder: "all"
                  "0.1.1":
                    folder: "all"
                foobar:
                  "0.1.0":
                    folder: "all"
                """)
    conandata_yml = textwrap.dedent(f"""
                sources:
                  "0.1.0":
                    sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                    url: "http://foobar.com/downloads/0.1.0.tar.gz"
                  "0.1.1":
                    sha256: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                    url: "http://foobar.com/downloads/0.1.1.tar.gz"
                """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)

    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add package'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


def test_add_extra_entry_in_config_version():
    """
    Only folder should be allowed under versions in config.yml to be classified as bump version
    """
    config_yml = textwrap.dedent(f"""
                    versions:
                      "0.1.0":
                        folder: "all"
                      "0.1.1":
                        folder: "all"
                        description: "Version 0.1.1"
                    """)
    conandata_yml = textwrap.dedent(f"""
                    sources:
                      "0.1.0":
                        sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                        url: "http://foobar.com/downloads/0.1.0.tar.gz"
                      "0.1.1":
                        sha256: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                        url: "http://foobar.com/downloads/0.1.1.tar.gz"
                    """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)

    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add package'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


def test_replace_version():
    """
    Replacing a version should be classified as bump version
    """
    _save_config_conandata("0.2.0")
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add version 0.2.0'")

    _save_config_conandata("0.3.0")
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add version 0.3.0'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


def test_remove_version():
    """
    Remove a version should not be classified as bump version
    """
    _save_config_conandata("0.2.0")
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add version 0.2.0'")

    config_yml = textwrap.dedent("""
                versions:
                  "0.1.0":
                    folder: "all"
                """)
    conandata_yml = textwrap.dedent("""
                sources:
                  "0.1.0":
                    sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                    url: "http://foobar.com/downloads/0.1.0.tar.gz"
                """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'remove version 0.2.0'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


def test_change_checksum():
    """
    Changing checksum should not be classified as bump version
    """
    conandata_yml = textwrap.dedent("""
                sources:
                  "0.1.0":
                    sha256: "9693387b9bc697799a4249d34946827549b81bb03f4ff6847e9b12b6a750ef46"
                    url: "http://foobar.com/downloads/0.1.0.tar.gz"
                """)
    save("all/conandata.yml", conandata_yml)
    run("git add all/conandata.yml")
    run("git commit -m 'Change checksum'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


def test_change_checksum_and_bump_version():
    """
    Changing checksum should not be classified as bump version when bumping a version
    """
    config_yml = textwrap.dedent(f"""
                        versions:
                          "0.1.0":
                            folder: "all"
                          "0.1.1":
                            folder: "all"
                        """)
    conandata_yml = textwrap.dedent(f"""
                        sources:
                          "0.1.0":
                            sha256: "9693387b9bc697799a4249d34946827549b81bb03f4ff6847e9b12b6a750ef46"
                            url: "http://foobar.com/downloads/0.1.0.tar.gz"
                          "0.1.1":
                            sha256: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                            url: "http://foobar.com/downloads/0.1.1.tar.gz"
                        """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Change checksum'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


def test_change_urn_and_bump_version():
    """
    The new version should have the same host as the previous version
    """
    config_yml = textwrap.dedent(f"""
                        versions:
                          "0.1.0":
                            folder: "all"
                          "0.1.1":
                            folder: "all"
                        """)
    conandata_yml = textwrap.dedent(f"""
                        sources:
                          "0.1.0":
                            sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                            url: "http://foobar.com/downloads/0.1.0.tar.gz"
                          "0.1.1":
                            sha256: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                            url: "http://acme.com/downloads/0.1.1.tar.gz"
                        """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Change checksum'")

    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    json_data = json.loads(load("output.json"))
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}
