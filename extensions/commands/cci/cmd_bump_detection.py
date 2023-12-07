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
conan bump-detection conan-center-index/recipes/boost
"""

import os
import json
import re
import subprocess
import inspect
import yaml

from conan.api.output import ConanOutput, cli_out_write
from conan.cli.command import conan_command, OnceArgument
from conan.errors import ConanException


def output_json(result):
    cli_out_write(json.dumps(result, indent=2, sort_keys=True))


def output_text(result):
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
    params = ['--name-only', '--relative'] if relative else ['--name-only']
    result = git_diff_regular(commit_hash_old, commit_hash_new, params)
    return [it for it in result.split('\n') if it != '']


def get_file_content_by_commit(commit_hash: str, file_path: str) -> str:
    try:
        result = subprocess.run(['git', 'show', f"{commit_hash}:{file_path}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ConanException(f"Could not show file content: {error}") from error


def load_yaml_content(file_content: str):
    try:
        return yaml.safe_load(file_content)
    except yaml.YAMLError as error:
        raise ConanException(f"Error loading YAML: {error}") from error


def get_config_yml_versions(commit_hash: str, yaml_path: str) -> list:
    yml_content = get_file_content_by_commit(commit_hash, yaml_path)
    config_yml = load_yaml_content(yml_content)
    versions = []
    if 'versions' in config_yml and isinstance(config_yml['versions'], list):
        versions = config_yml['versions']
    return versions


def recursive_yaml_diff(yaml_old, yaml_new):
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
    yml_content_old = get_file_content_by_commit(commit_hash_old, yaml_path)
    yml_content_new = get_file_content_by_commit(commit_hash_new, yaml_path)

    yaml_old = load_yaml_content(yml_content_old)
    yaml_new = load_yaml_content(yml_content_new)

    return recursive_yaml_diff(yaml_old, yaml_new)


def detect_bump_version(commit_hash_old: str, commit_hash_new: str, output: ConanOutput) -> list:
    current_frame = inspect.currentframe()
    output.debug(f"TRACE LINE: {inspect.getframeinfo(current_frame).lineno}")

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

    compare_result = compare_yaml_files(commit_hash_old, commit_hash_new, config_list[0])
    if compare_result.keys() != {'versions'}:
        # INFO: Only versions should be changed
        return []

    if not all('added' in version_info and len(version_info['added']) == 1 and 'folder' in version_info['added'] for version_info in compare_result['versions'].values()):
        # INFO: Only new versions should be added and the folder entry is allowed to versions
        return []

    added_versions = list(compare_result['versions'].keys())
    # INFO: Only semver and major.minor versions are allowed. Custom versions should be reviewed to avoid unexpected versions
    semver_pattern = re.compile(r'^(\d+)\.(\d+)(?:\.(\d+))?$')
    for version in added_versions:
        if not semver_pattern.match(version):
            output.warning(f"Found non-semver format added to config.yml: {version}. Skipping ...")
            return []

    # TODO: Parse conandata.yml and check if the new version is added

    return added_versions


@conan_command(group="Conan Center Index", formatters={"text": output_text, "json": output_json})
def bump_detection(_, parser, *args):
    """
    Detects bump version and bump dependencies in a recipe folder.
    """
    # TODO: Add support to recipe folder path
    # parser.add_argument('path', help="Path to package folder e.g. recipes/boost")
    parser.add_argument('-o', '--old-commit', action=OnceArgument, help="Git commit hash of the older branch", default='master')
    parser.add_argument('-n', '--new-commit', action=OnceArgument, help="Git commit hash of branch with new changes", default='HEAD')
    args = parser.parse_args(*args)

    out = ConanOutput()
    old_commit = get_branch_commit_hash(args.old_commit)
    current_commit = get_branch_commit_hash(args.new_commit)

    out.info(f"Old Git hash commit: {old_commit}")
    out.info(f"New Git hash commit: {current_commit}")

    bump_version = detect_bump_version(old_commit, current_commit, out)
    bump_requirements = []
    bump_tools_requirements = []
    bump_test_requirements = []

    return {"bump_version": bump_version,
            "bump_requirements": bump_requirements,
            "bump_tools_requirements": bump_tools_requirements,
            "bump_test_requirements": bump_test_requirements,}
