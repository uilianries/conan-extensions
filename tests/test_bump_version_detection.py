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


def _git_add_commit_conan_run() -> dict:
    """
    Commit config.yml and conandata.yml and run bump-detection

    :return: bump-detection output
    """
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Update version'")
    run("conan cci:bump-detection --old-commit=HEAD~1 --new-commit=HEAD  --format json > output.json")
    return json.loads(load("output.json"))


def _commit_and_check_no_bump_version():
    json_data = _git_add_commit_conan_run()
    assert json_data == {"bump_version": [], "bump_requirements": [], "bump_tools_requirements": [],
                         "bump_test_requirements": []}


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
    json_data = _git_add_commit_conan_run()
    assert json_data == {"bump_version": expected_bump_version, "bump_requirements": [],
                         "bump_tools_requirements": [], "bump_test_requirements": []}


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
    _commit_and_check_no_bump_version()


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
    _commit_and_check_no_bump_version()


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
    _commit_and_check_no_bump_version()


def test_replace_version():
    """
    Replacing a version should be classified as bump version
    """
    _save_config_conandata("0.2.0")
    run("git add config.yml all/conandata.yml")
    run("git commit -m 'Add version 0.2.0'")

    _save_config_conandata("0.3.0")
    _commit_and_check_no_bump_version()


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
    _commit_and_check_no_bump_version()


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
    _commit_and_check_no_bump_version()


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
    _commit_and_check_no_bump_version()


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
    _commit_and_check_no_bump_version()


def test_add_extra_version_in_config():
    """
    Versions should match between config.yml and conandata.yml
    """
    config_yml = textwrap.dedent(f"""
                    versions:
                      "0.1.0":
                        folder: "all"
                      "0.1.1":
                        folder: "all"
                      "0.2.0":
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
    _commit_and_check_no_bump_version()


def test_add_sha1_as_checksum():
    """
    Only sha256 is allowed as checksum to be classified as bump version
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
                        sha1: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                        url: "http://foobar.com/downloads/0.1.1.tar.gz"
                    """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)
    _commit_and_check_no_bump_version()


def test_add_only_config_yml():
    """
    Adding only new version in config.yml should not be classified as bump version
    """
    config_yml = textwrap.dedent(f"""
                    versions:
                      "0.1.0":
                        folder: "all"
                      "0.1.1":
                        folder: "all"                      
                    """)
    save("config.yml", config_yml)
    _commit_and_check_no_bump_version()


def test_add_only_conandata_yml():
    """
    Adding only new version in conandata.yml should not be classified as bump version
    """
    conandata_yml = textwrap.dedent(f"""
                        sources:
                          "0.1.0":
                            sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                            url: "http://foobar.com/downloads/0.1.0.tar.gz"
                          "0.1.1":
                            sha1: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                            url: "http://foobar.com/downloads/0.1.1.tar.gz"
                        """)
    save("all/conandata.yml", conandata_yml)
    _commit_and_check_no_bump_version()


def test_add_mirrors():
    """
    Adding mirrors should be classified as bump version, only if previous version has mirrors and with same host
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
                        url: 
                        - "http://foobar.com/downloads/0.1.1.tar.gz"
                        - "http://mirror.com/downloads/0.1.1.tar.gz"
                    """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)

    # No mirrors in previous version, no bump version allowed
    _commit_and_check_no_bump_version()

    # Added mirrors in previous version, bump version matched
    config_yml = textwrap.dedent(f"""
                        versions:
                          "0.1.0":
                            folder: "all"
                          "0.1.1":
                            folder: "all"
                          "0.2.0":
                            folder: "all"
                        """)
    conandata_yml = textwrap.dedent(f"""
                        sources:
                          "0.1.0":
                            sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                            url: "http://foobar.com/downloads/0.1.0.tar.gz"
                          "0.1.1":
                            sha256: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                            url: 
                            - "http://foobar.com/downloads/0.1.1.tar.gz"
                            - "http://mirror.com/downloads/0.1.1.tar.gz"
                          "0.2.0":
                            sha256: "9fc590e69c74d61c17b814e641f1c4e70094b80f2ab2245179ebf3a2cf82a5a1"
                            url: 
                            - "http://foobar.com/downloads/0.1.1.tar.gz"
                            - "http://mirror.com/downloads/0.2.0.tar.gz"
                        """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)
    json_data = _git_add_commit_conan_run()
    assert json_data == {"bump_version": ["0.2.0"], "bump_requirements": [],
                         "bump_tools_requirements": [], "bump_test_requirements": []}

    # No multiple sha256 should be allowed, mirrors should use only the same sha256
    config_yml = textwrap.dedent(f"""
                            versions:
                              "0.1.0":
                                folder: "all"
                              "0.1.1":
                                folder: "all"
                              "0.2.0":
                                folder: "all"
                              "0.2.1":
                                folder: "all"
                            """)
    conandata_yml = textwrap.dedent(f"""
                            sources:
                              "0.1.0":
                                sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                                url: "http://foobar.com/downloads/0.1.0.tar.gz"
                              "0.1.1":
                                sha256: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                                url: 
                                - "http://foobar.com/downloads/0.1.1.tar.gz"
                                - "http://mirror.com/downloads/0.1.1.tar.gz"
                              "0.2.0":
                                sha256: "9fc590e69c74d61c17b814e641f1c4e70094b80f2ab2245179ebf3a2cf82a5a1"
                                url: 
                                - "http://foobar.com/downloads/0.1.1.tar.gz"
                                - "http://mirror.com/downloads/0.2.0.tar.gz"
                              "0.2.1":
                                sha256:
                                - "9fc590e69c74d61c17b814e641f1c4e70094b80f2ab2245179ebf3a2cf82a5a1"
                                - "f07a5f70c94fa8d912a898c7b859c9fd97ccc5173a99e452a584ecd2a0c61222"
                                url: 
                                - "http://foobar.com/downloads/0.2.1.tar.gz"
                                - "http://mirror.com/downloads/0.2.1.tar.gz"
                            """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)
    _commit_and_check_no_bump_version()


def test_add_patches():
    """
    Adding patches or re-using patches from previous version should not be classified as bump version
    """
    conandata_yml = textwrap.dedent(f"""
                                sources:
                                  "0.1.0":
                                    sha256: "507eb7b8d1015fbec5b935f34ebed15bf346bed04a11ab82b8eee848c4205aea"
                                    url: "http://foobar.com/downloads/0.1.0.tar.gz"
                                patches:
                                  "1.0.0":
                                    - patch_file: "patches/0001-fpic-honor.patch"
                                      patch_description: "Conan should manage fpic flag"
                                      patch_type: "conan"                                                                                
                                """)
    save("all/conandata.yml", conandata_yml)
    run("git add all/conandata.yml")
    run("git commit -m 'Add patches'")
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
                            sha1: "f0471ff5f578e2e71673470f9703d453794d6c014c5448511afa0077e0a16a4a"
                            url: "http://foobar.com/downloads/0.1.1.tar.gz"
                          patches:
                            "1.0.0":
                              - patch_file: "patches/0001-fpic-honor.patch"
                                patch_description: "Conan should manage fpic flag"
                                patch_type: "conan"
                            "1.1.0":
                              - patch_file: "patches/0001-fpic-honor.patch"
                                patch_description: "Conan should manage fpic flag"
                                patch_type: "conan"
                        """)
    save("config.yml", config_yml)
    save("all/conandata.yml", conandata_yml)
    _commit_and_check_no_bump_version()
