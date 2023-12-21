"""
This Conan extension detects if a workspace has a bump version or bump dependency based on a previous commit hash.

The follow steps and rules are applied:
- It does a git diff between the master branch and the current branch by default.
- Read config.yml file from the master branch and the current branch.
- The newer branch must have the same versions as the master branch, plus one or more versions.
- Only semver (without pre-release) and major.minor versions are supported. Skipping if other formats are found.
- The conandata.yml file must have the same versions than the config.yml file for both branches.
- Adding new patches to a new version is not considered a bump version.
- The URL (hostname) of the new version must be the same as the URL of the previous version.

Usage:
conan bump-detection --old-commit=origin/master/refs/HEAD --new-commit=HEAD --format=json
{"bump_version": "0.1.0", "bump_requirements": [], "bump_tools_requirements": [], "bump_test_requirements": []}
"""

import os
import json
import re
import subprocess
from urllib.parse import urlparse
import yaml
from conan.api.output import ConanOutput, cli_out_write
from conan.cli.command import conan_command, OnceArgument
from conan.errors import ConanException


def output_json(result):
    """
    Output the result as JSON
    """
    cli_out_write(json.dumps(result, indent=2, sort_keys=True))


def output_text(result):
    """
    Output the result as friendly text
    """
    cli_out_write(f"BUMP VERSION: {bool(result.get('bump_version'))}")
    bump_dependencies = bool(result.get("bump_requirements") or result.get("bump_tools_requirements") or result.get("bump_test_requirements"))
    if result["bump_version"]:
        cli_out_write("BUMP VERSION LIST")
        cli_out_write(f"{', '.join(result['bump_version'])}")
    cli_out_write(f"BUMP DEPENDENCIES: {bump_dependencies}")
    if result['bump_requirements']:
        cli_out_write("BUMP REQUIREMENTS LIST")
        cli_out_write(f"{', '.join(result['bump_requirements'])}")
    if result['bump_tools_requirements']:
        cli_out_write("BUMP TOOLS REQUIREMENTS LIST")
        cli_out_write(f"{', '.join(result['bump_tools_requirements'])}")
    if result['bump_test_requirements']:
        cli_out_write("BUMP TEST REQUIREMENTS LIST")
        cli_out_write(f"{', '.join(result['bump_test_requirements'])}")
    cli_out_write("")


def get_branch_commit_hash(branch_name: str) -> str:
    """
    Detect a git hash commit from a git branch name in the local copy of the repository

    :param branch_name: A git branch name
    :return: The git commit hash
    :raises ConanException: If some error occurs when executing git command
    """
    try:
        result = subprocess.run(['git', 'rev-parse', branch_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ConanException(f"Could not get git branch commit: {error}") from error


def git_diff_regular(commit_hash_old: str, commit_hash_new: str, kwargs=()) -> str:
    """
    Get git diff output content from two different git branches

    """
    try:
        result = subprocess.run(['git', 'diff', *kwargs, commit_hash_old, commit_hash_new], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as error:
        raise ConanException(f"Could not run git diff: {error}") from error


def git_diff_filenames(commit_hash_old: str, commit_hash_new: str, relative=False) -> list:
    """
    Get the list of files changed between two git commit hashes

    :param commit_hash_old: The git commit hash of the old branch
    :param commit_hash_new: The git commit hash of the new branch
    :param relative: Return the relative path of the files
    :return: The list of files changed between the two git commit hashes
    """
    params = ['--name-only', '--relative'] if relative else ['--name-only']
    result = git_diff_regular(commit_hash_old, commit_hash_new, params)
    return [it for it in result.split('\n') if it != '']


def get_file_content_by_commit(commit_hash: str, file_path: str) -> str:
    """
    Get the content of a file from a git commit hash

    :param commit_hash: The git commit hash
    :param file_path: The path of the file
    :return: The content of the file as string
    """
    try:
        result = subprocess.run(['git', 'show', f"{commit_hash}:{file_path}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ConanException(f"Could not show file content: {error}") from error


def load_yaml_content(file_content: str) -> dict:
    """
    Load YAML content from a file content as string.
    In case of error, it raises a ConanException

    :param file_content: The file content as string
    :return: The YAML content as dictionary
    """
    try:
        return yaml.safe_load(file_content)
    except yaml.YAMLError as error:
        raise ConanException(f"Error loading YAML: {error}") from error


def get_config_yml_versions(commit_hash: str, yaml_path: str) -> list:
    """
    Get the list of package versions from a config.yml file

    :param commit_hash: The git commit hash of the config.yml file
    :param yaml_path: The path of the config.yml file
    :return: The list of package versions
    """
    yml_content = get_file_content_by_commit(commit_hash, yaml_path)
    config_yml = load_yaml_content(yml_content)
    versions = []
    if 'versions' in config_yml and isinstance(config_yml['versions'], dict):
        versions = list(config_yml['versions'].keys())
    return versions


def get_conandata_yml_versions(commit_hash: str, yaml_path: str) -> list:
    """
    Get the list of package versions from a conandata.yml file

    :param commit_hash: The git commit hash of the conandata.yml file
    :param yaml_path: The path of the conandata.yml file
    :return: The list of package versions
    """
    yml_content = get_file_content_by_commit(commit_hash, yaml_path)
    conandata_yml = load_yaml_content(yml_content)
    versions = []
    if 'sources' in conandata_yml and isinstance(conandata_yml['sources'], dict):
        versions = list(conandata_yml['sources'].keys())
    return versions


def get_conandata_yml_urls(commit_hash: str, yaml_path: str) -> list:
    """
    Get the list of urls listed in a conandata.yml file

    :param commit_hash: The git commit hash of the conandata.yml file
    :param yaml_path: The path of the conandata.yml file
    :return: The list of hostnames used in the urls of the conandata.yml file
    """
    yml_content = get_file_content_by_commit(commit_hash, yaml_path)
    conandata_yml = load_yaml_content(yml_content)
    urls = []
    if 'sources' in conandata_yml and isinstance(conandata_yml['sources'], dict):
        for version_it in conandata_yml['sources'].values():
            if 'url' in version_it and isinstance(version_it['url'], str):
                urls.append(urlparse(version_it['url']))
            elif 'url' in version_it and isinstance(version_it['url'], list):
                urls.extend([urlparse(url) for url in version_it['url']])
    return urls


def recursive_yaml_diff(yaml_old, yaml_new):
    """
    Compare two YAML files and return the differences

    :param yaml_old: The old YAML content
    :param yaml_new: The new YAML content
    :return: The differences between the two YAML files

    It returns a dictionary with the following structure:
    added: The new entry added to the new YAML file
    removed: The entry removed from the old YAML file
    modified: The entry modified from the old YAML file
    """
    differences = {}
    keys = set(yaml_old) | set(yaml_new)

    for key in keys:
        if key not in yaml_old:
            differences[key] = {'added': yaml_new[key]}
        elif key not in yaml_new:
            differences[key] = {'removed': yaml_old[key]}
        elif yaml_old[key] != yaml_new[key]:
            if isinstance(yaml_old[key], dict) and isinstance(yaml_new[key], dict):
                differences[key] = recursive_yaml_diff(yaml_old[key], yaml_new[key])
            else:
                differences[key] = {'modified': {'old': yaml_old[key], 'new': yaml_new[key]}}

    return differences


def compare_yaml_files(commit_hash_old: str, commit_hash_new: str, yaml_path: str) -> dict:
    """
    Compare two YAML files and return the differences, based on a git commit hash

    :param commit_hash_old: The git commit hash of the old YAML file
    :param commit_hash_new: The git commit hash of the new YAML file
    :param yaml_path: The path of the YAML file
    :return: The differences between the two YAML files
    """
    yml_content_old = get_file_content_by_commit(commit_hash_old, yaml_path)
    yml_content_new = get_file_content_by_commit(commit_hash_new, yaml_path)

    yaml_old = load_yaml_content(yml_content_old)
    yaml_new = load_yaml_content(yml_content_new)

    return recursive_yaml_diff(yaml_old, yaml_new)


def detect_bump_version(commit_hash_old: str, commit_hash_new: str, output: ConanOutput) -> list:
    """
    Detect if a recipe folder has a bump version based on a previous commit hash.
    In case of return an empty list, it means that the recipe folder does not have a bump version.

    :param commit_hash_old: The git commit hash of the old branch
    :param commit_hash_new: The git commit hash of the new branch
    :param output: The Conan output
    :return: The list of valid new versions added to the recipe folder
    """
    files = git_diff_filenames(commit_hash_old, commit_hash_new, relative=True)
    # INFO: Expects only two files: config.yml and conandata.yml
    if len(files) != 2:
        return []

    common_prefix = os.path.commonprefix([os.path.abspath(it) for it in files])
    common_prefix = os.path.relpath(common_prefix)
    # INFO: conandata.yml and config.yml must be from the same recipe folder
    if not os.path.isdir(common_prefix):
        return []

    files = git_diff_filenames(commit_hash_old, commit_hash_new, relative=False)
    config_list = [it for it in files if os.path.basename(it) == 'config.yml']
    # INFO: Only one config.yml file is allowed
    if len(config_list) != 1:
        return []

    conandata_list = [it for it in files if os.path.basename(it) == 'conandata.yml']
    # TODO: Support multiple conandata.yml files
    if len(conandata_list) != 1:
        return []

    # INFO: CONFIG.YML CHECKS

    config_compare_result = compare_yaml_files(commit_hash_old, commit_hash_new, config_list[0])
    if config_compare_result.keys() != {'versions'}:
        # INFO: Only versions should be changed
        return []

    for version_info in config_compare_result['versions'].values():
        if 'added' not in version_info or len(version_info['added']) != 1 or len(version_info.keys()) != 1 or 'folder' not in version_info['added']:
            # INFO: Only new versions should be added and the folder entry is allowed to versions. No other entries are allowed and no changes or removes are allowed.
            return []

    added_versions = list(config_compare_result['versions'].keys())
    # INFO: Only semver and major.minor versions are allowed. Custom versions should be reviewed to avoid unexpected versions
    semver_pattern = re.compile(r'^(\d+)\.(\d+)(?:\.(\d+))?$')
    for version in added_versions:
        if not semver_pattern.match(version):
            output.warning(f"Found non-semver format added to config.yml: {version}. Skipping ...")
            return []

    config_yml_versions = get_config_yml_versions(commit_hash_new, config_list[0])
    conandata_yaml_versions = get_conandata_yml_versions(commit_hash_new, conandata_list[0])
    if sorted(config_yml_versions) != sorted(conandata_yaml_versions):
        # INFO: The versions in config.yml and conandata.yml must be the same
        return []

    # INFO: CONANDATA.YML CHECKS

    conandata_compare_result = compare_yaml_files(commit_hash_old, commit_hash_new, conandata_list[0])
    if conandata_compare_result.keys() != {'sources'}:
        # INFO: Only versions in sources should be changed
        return []

    for version_info in conandata_compare_result['sources'].values():
        if version_info.keys() != {'added'}:
            # INFO: Only new versions should be added. No remove neither changes are allowed
            return []

        if len(version_info['added'].keys()) != 2 or not all(key in version_info['added'].keys() for key in ('url', 'sha256')):
            # INFO: Only url and sha256 entries are allowed to be added
            return []

        if not isinstance(version_info['added']['sha256'], str):
            # INFO: Only one sha256 entry is allowed per version, so mirrors should use the very checksum always
            return []

        old_url_hostnames = get_conandata_yml_urls(commit_hash_old, conandata_list[0])
        add_urls = version_info['added']['url']
        add_urls = [add_urls] if isinstance(add_urls, str) else add_urls
        if not all(urlparse(url).hostname in [it.hostname for it in old_url_hostnames] for url in add_urls):
            # INFO: The URL of the new version must be the same as the URL of the previous version
            return []
        if not all(urlparse(url).scheme in [it.scheme for it in old_url_hostnames] for url in add_urls):
            # INFO: The scheme (e.g. https) of the new version must be the same as the URL of the previous versions
            return []

    return added_versions


def detect_bump_requirements(commit_hash_old: str, commit_hash_new: str, output: ConanOutput) -> list:
    """
    Detect if a Conanfile recipe has a bump dependency based on a previous commit hash.
    In case of return an empty list, it means that the recipe folder does not have a bump dependency.

    :param commit_hash_old: The git commit hash of the old branch
    :param commit_hash_new: The git commit hash of the new branch
    :param output: The Conan output
    :return: The list of valid new references updated in the requirements of the conanfile.py
    """
    # TODO: Implement this function
    return []


def detect_bump_tool_requirements(commit_hash_old: str, commit_hash_new: str, output: ConanOutput) -> list:
    """
    Detect if a Conanfile recipe has a bump of tool dependencies based on a previous commit hash.
    In case of return an empty list, it means that the recipe folder does not have a bump tool dependency.

    :param commit_hash_old: The git commit hash of the old branch
    :param commit_hash_new: The git commit hash of the new branch
    :param output: The Conan output
    :return: The list of valid new references updated in the tools requirements of the conanfile.py
    """
    # TODO: Implement this function
    return []


def detect_bump_test_requirements(commit_hash_old: str, commit_hash_new: str, output: ConanOutput) -> list:
    """
    Detect if a Conanfile recipe has a bump of test dependencies based on a previous commit hash.
    In case of return an empty list, it means that the recipe folder does not have a test tool dependency.

    :param commit_hash_old: The git commit hash of the old branch
    :param commit_hash_new: The git commit hash of the new branch
    :param output: The Conan output
    :return: The list of valid new references updated in the test requirements of the conanfile.py
    """
    # TODO: Implement this function
    return []


@conan_command(group="Conan Center Index", formatters={"text": output_text, "json": output_json})
def bump_detection(_, parser, *args):
    """
    Detects bump version and bump dependencies in a recipe folder.
    """
    # TODO: Add support to recipe folder path
    # parser.add_argument('path', help="Path to package folder e.g. recipes/boost")
    parser.add_argument('-o', '--old-commit', action=OnceArgument, help="Git commit hash of the older branch", default='origin/master/refs/HEAD')
    parser.add_argument('-n', '--new-commit', action=OnceArgument, help="Git commit hash of branch with new changes", default='HEAD')
    args = parser.parse_args(*args)

    out = ConanOutput()
    old_commit = get_branch_commit_hash(args.old_commit)
    current_commit = get_branch_commit_hash(args.new_commit)

    out.info(f"Old Git hash commit: {old_commit}")
    out.info(f"New Git hash commit: {current_commit}")

    return {"bump_version": detect_bump_version(old_commit, current_commit, out),
            "bump_requirements": detect_bump_requirements(old_commit, current_commit, out),
            "bump_tools_requirements": detect_bump_tool_requirements(old_commit, current_commit, out),
            "bump_test_requirements": detect_bump_test_requirements(old_commit, current_commit, out)}
