#!/usr/bin/env python3

import argparse
import functools
import io
import json
import os
import re
import requests
import sys
import unidiff
import xml.etree.ElementTree as ET

FILE_EXTENSIONS_TO_CONSIDER = [".kt", ".java", ".kts"]

def load_ignore_files_patterns():
    regexes = os.environ.get("INPUT_IGNORE_FILE_PATTERNS")
    if regexes:
        return json.loads(regexes)
    else:
        return []

ignore_files_patterns = load_ignore_files_patterns()

def stderr(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


@functools.total_ordering
class Diagnostic:
    def __init__(self, file_name, line_number, error_level, description):
        self.file_name = file_name
        self.line_number = line_number
        self.description = description
        self.error_level = error_level

    def __eq__(self, other):
        return (
            self.file_name.lower(),
            self.line_number,
            self.error_level,
            self.description,
        ) == (
            other.file_name.lower(),
            other.line_number,
            other.error_level,
            other.description,
        )

    def __lt__(self, other):
        return (
            self.file_name.lower(),
            self.line_number,
            self.error_level,
            self.description,
        ) < (
            other.file_name.lower(),
            other.line_number,
            other.error_level,
            other.description,
        )


def assert_200_response(res, msg):
    if res.status_code != 200:
        stderr(msg)
        stderr("Response status code:", res.status_code)
        stderr("Response body:\n", res.text)
        sys.exit(-1)


def analyze_file(path):
    diagnostics = []
    with io.open(path, encoding="utf-8") as fin:
        text = fin.read()
    text = text.replace('<?xml version="1.0" encoding="UTF-8"?>', "")
    text = text.replace("file://$PROJECT_DIR$/", "")
    text = text.replace("</problems>", "") + "</problems>"
    tree = ET.fromstring(text)
    for problem in tree.iter("problem"):
        file_name = problem.find("file").text
        _, file_ext = os.path.splitext(file_name)
        if file_ext.lower() not in FILE_EXTENSIONS_TO_CONSIDER:
            continue
        if(check_file_name_for_regex_patterns(file_name)):
            continue
        line_no = int(problem.find("line").text)
        error_level = problem.find("problem_class").get("severity")
        description = (
            problem.find("description")
            .text.replace("#loc", "")
            .replace("<code>", "`")
            .replace("</code>", "`")
            .strip()
        )
        diagnostics.append(Diagnostic(file_name, line_no, error_level, description))
    return diagnostics


def get_diff_from_pr(repo, pr, token):
    url = url = "https://api.github.com/repos/{}/pulls/{}".format(repo, pr)
    headers = {
        "Authorization": "token " + token,
        "Accept": "application/vnd.github.VERSION.diff",
        "User-Agent": "gps/intellij-inspections-action",
    }
    res = requests.get(url, headers=headers)
    assert_200_response(res, "Unable to get diff from PR")
    return res.text


def find_position(ps, path, line):
    for pf in ps:
        if pf.path != path:
            continue
        pos = 0
        for hunk in pf:
            for diff_line in hunk:
                pos += 1
                if diff_line.target_line_no == line:
                    return pos


def comment_on_pr(diagnostics, repo, pr, token):
    headers = {
        "Authorization": "token " + token,
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "gps/intellij-inspections-action",
    }
    url = "https://api.github.com/repos/{}/pulls/{}/reviews".format(repo, pr)
    diff = get_diff_from_pr(repo, pr, token)
    ps = unidiff.PatchSet(diff)
    comments = []
    unknown = []
    for diagnostic in diagnostics:
        if diagnostic.error_level not in ["WARNING", "ERROR"]:
            continue
        pos = find_position(ps, diagnostic.file_name, diagnostic.line_number)
        if pos:
            comments.append(
                {
                    "body": diagnostic.description,
                    "path": diagnostic.file_name,
                    "position": pos,
                }
            )
        else:
            if diagnostic.error_level in ["WARNING", "ERROR"]:
                unknown.append(diagnostic)
    event = "COMMENT"
    text = ""
    num_errors = sum(1 if d.error_level == "ERROR" else 0 for d in diagnostics)
    num_warnings = sum(1 if d.error_level == "WARNING" else 0 for d in diagnostics)
    if num_errors == 0:
        event = "APPROVE"
        if num_warnings == 0:
            text = "🎉 Excellent, your code has passed all inspections! 🎉"
        else:
            text = "Your code has no inspection errors, but there are a few warnings. Please check the warnings."
    elif num_errors > 1:
        event = "REQUEST_CHANGES"
        text = "‼️ Your code has errors - please fix them ‼️"
    if unknown:
        text += "\n\nThis branch has errors or warnings, but they are not part of the diff:\n\n"
        for diagnostic in unknown:
            text += "Path: {}\nLine number: {}\nLevel: {}\n Problem:{}\n".format(
                diagnostic.file_name,
                diagnostic.line_number,
                diagnostic.error_level,
                diagnostic.description,
            )
    body = {"event": event, "comments": comments, "body": text}
    res = requests.post(url, headers=headers, data=json.dumps(body))
    assert_200_response(res, "Unable to review PR")


def compare_diagnostics(left, right):
    return cmp(left.file_name, right.file_name)


def print_report(diagnostics):
    diagnostics = sorted(diagnostics)
    for diagnostic in diagnostics:
        print("Path:", diagnostic.file_name)
        print("Level:", diagnostic.error_level)
        print("Line:", diagnostic.line_number)
        print("Error:", diagnostic.description)

def check_file_name_for_regex_patterns(file_name):
    for regex in ignore_files_patterns:
        if re.match(regex,file_name):
            print("Inspection results for file ignored:",file_name)
            return True
    return False

def main():
    parser = argparse.ArgumentParser("Analyzes IntelliJ Inspections")
    parser.add_argument(
        "-i", "--inspections", required=True, help="Path to inspections folder"
    )
    args = parser.parse_args()

    ins = os.path.abspath(args.inspections)
    files = [
        os.path.join(ins, f)
        for f in os.listdir(ins)
        if f.endswith(".xml") and not f.startswith(".")
    ]

    diagnostics = []

    for f in files:
        diagnostics.extend(analyze_file(f))

    output = {"diagnostics": diagnostics}
    analysis = json.dumps(output, indent=4, default=lambda x: x.__dict__)
    with open(os.path.join(ins, "analysis.json"), "w") as fout:
        fout.write(analysis)

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        stderr("Unable to determine GitHub repo, cannot comment on PR")
        sys.exit(-1)
    print("Repo:", repo)
    token = os.environ.get("INPUT_GH_TOKEN")
    if not token:
        stderr("Unable to get GitHub token, cannot comment on PR")
        sys.exit(-1)
    ref = os.environ.get("GITHUB_REF")
    print("REF:", ref)
    if ref and ref.startswith("refs/pull/"):
        pr = int(ref.replace("refs/pull/", "").replace("/merge", ""))
        print("PR Number:", pr)
        comment_on_pr(diagnostics, repo, pr, token)

    print_report(diagnostics)

    num_errors = sum(1 if d.error_level == "ERROR" else 0 for d in diagnostics)
    if num_errors > 0:
        sys.exit(-1)


if __name__ == "__main__":
    main()
