"""Select CI ownership, record the tested checkout and enforce the required gate."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request


def check_ownership(event_name, event, repository, ref, sha, fetch_pulls, fetch_runs):
    """Only suppress a development push already covered by a matching open PR.

    PRs test the GitHub merge checkout. Main and manual runs always run in full.
    A failed API query duplicates work rather than silently losing coverage.
    """
    branch = ref.removeprefix("refs/heads/")
    default_branch = event.get("repository", {}).get("default_branch")
    if event_name != "push" or not ref.startswith("refs/heads/") or not default_branch or branch == default_branch:
        return True, "", "This event owns its CI checks."
    try:
        pulls = fetch_pulls(repository, branch)
        if not isinstance(pulls, list):
            raise ValueError("Expected a list of pull requests")
        matching_numbers = []
        for pull in pulls:
            head = pull.get("head", {})
            number = pull.get("number")
            if (pull.get("state") == "open" and type(number) is int and number > 0
                    and head.get("sha") == sha and head.get("ref") == branch
                    and (head.get("repo") or {}).get("full_name") == repository):
                matching_numbers.append(number)
        # An open PR alone is insufficient: merge-conflicted PRs do not receive
        # pull_request workflow runs. Only an observed matching run owns coverage.
        if matching_numbers:
            runs = fetch_runs(repository, sha)
            if not isinstance(runs, dict) or not isinstance(runs.get("workflow_runs"), list):
                raise ValueError("Expected workflow runs")
            for run in runs["workflow_runs"]:
                active = run.get("status") in {"queued", "in_progress"}
                finished = run.get("status") == "completed" and run.get("conclusion") in {"success", "failure"}
                if run.get("event") != "pull_request" or run.get("head_sha") != sha or not (active or finished):
                    continue
                for pull in run.get("pull_requests", []):
                    number = pull.get("number")
                    if number in matching_numbers:
                        return False, str(number), f"Observed PR #{number} CI run owns checks for this push."
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return True, "", "PR lookup unavailable; run checks to preserve coverage."
    return True, "", "No matching open PR; run development-branch checks."


def github_json(path, query):
    url = f"{os.environ['GITHUB_API_URL']}/{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def github_pulls(repository, branch):
    owner = repository.split("/", 1)[0]
    return github_json(f"repos/{repository}/pulls", {
        "head": f"{owner}:{branch}", "state": "open", "per_page": 100,
    })


def github_runs(repository, sha):
    return github_json(f"repos/{repository}/actions/workflows/ci.yml/runs", {
        "event": "pull_request", "head_sha": sha, "per_page": 100,
    })


def gate_errors(results, *, event_name, ref):
    """Missing, skipped or cancelled mandatory jobs must never turn green."""
    errors = []
    changes = results.get("changes", {})
    outputs = changes.get("outputs", {})
    if changes.get("result") != "success":
        errors.append("change selection did not succeed")
    selected = outputs.get("run_checks")
    if selected == "false":
        duplicate = outputs.get("duplicate_pr", "")
        if (event_name != "push" or ref == "refs/heads/main"
                or not ref.startswith("refs/heads/") or not duplicate.isdecimal()
                or int(duplicate) < 1):
            errors.append("only a matching development-branch push may delegate checks to a PR")
        expected = dict.fromkeys(("linux-checks", "windows-checks", "scientific", "runtime", "packaging"), "skipped")
    else:
        if selected != "true":
            errors.append("unknown check-ownership decision")
        expected = {"linux-checks": "success", "windows-checks": "success"}
        for layer in ("scientific", "runtime", "packaging"):
            selected_layer = outputs.get(layer)
            if selected_layer not in {"true", "false"}:
                errors.append(f"unknown {layer} selection")
            expected[layer] = "success" if selected_layer == "true" else "skipped"
    for name, result in expected.items():
        actual = results.get(name, {}).get("result")
        if actual != result:
            errors.append(f"{name}: {actual}; expected {result}")
    return errors


def source_record(event_name, event, *, repository=Path(".")):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repository, text=True).strip()
    return {
        "event": event_name,
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "event_sha": os.environ.get("GITHUB_SHA", ""),
        "pull_request_head": event.get("pull_request", {}).get("head", {}).get("sha", ""),
    }


def write_outputs(values):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                raise ValueError("Output values must be single-line")
            handle.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("ownership", "source", "gate"))
    args = parser.parse_args()
    if args.command == "gate":
        results = json.loads(os.environ["CHECK_RESULTS"])
        errors = gate_errors(results, event_name=os.environ["GITHUB_EVENT_NAME"], ref=os.environ["GITHUB_REF"])
        if errors:
            raise SystemExit("CI failed: " + "; ".join(errors))
        print("All applicable checks passed. " + results["changes"]["outputs"].get("ownership_reason", ""))
        return
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    event_name = os.environ["GITHUB_EVENT_NAME"]
    if args.command == "ownership":
        run, duplicate, reason = check_ownership(
            event_name, event, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF"],
            os.environ["GITHUB_SHA"], github_pulls, github_runs,
        )
        write_outputs({"run_checks": str(run).lower(), "duplicate_pr": duplicate, "ownership_reason": reason})
        print(reason)
        return
    record = source_record(event_name, event)
    write_outputs(record)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write("## Tested source\n\n")
        for label, key in (("Event", "event"), ("Checkout / manifest commit", "source_commit"),
                           ("Git tree", "source_tree"), ("Event SHA", "event_sha"),
                           ("PR branch head (if applicable)", "pull_request_head")):
            summary.write(f"- {label}: `{record[key] or 'not applicable'}`\n")
        summary.write("\nPR checks use the merge checkout; its commit can differ from the branch head. "
                      "Installer manifests always identify the actual checkout.\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
