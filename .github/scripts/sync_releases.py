from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Release:
    tag: str
    name: str
    body: str
    prerelease: bool
    draft: bool
    html_url: str


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    ok_statuses: tuple[int, ...] = (200, 201, 202, 204),
) -> Any:
    body = None
    merged_headers = {"Accept": "application/json", **headers}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        merged_headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=merged_headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            if response.status not in ok_statuses:
                raise RuntimeError(f"{method} {url} returned {response.status}: {raw!r}")
            return json.loads(raw.decode("utf-8")) if raw else None
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        if error.code not in ok_statuses:
            raise RuntimeError(f"{method} {url} returned {error.code}: {raw}") from error
        return None


def load_release() -> tuple[str, Release]:
    with open(env("GITHUB_EVENT_PATH"), encoding="utf-8") as event_file:
        event = json.load(event_file)

    raw = event.get("release") or {}
    tag = raw.get("tag_name") or event.get("ref")
    if not tag:
        raise RuntimeError("Release tag was not found in event payload")

    return event.get("action", ""), Release(
        tag=tag,
        name=raw.get("name") or tag,
        body=raw.get("body") or "",
        prerelease=bool(raw.get("prerelease", False)),
        draft=bool(raw.get("draft", False)),
        html_url=raw.get("html_url") or f"https://github.com/{env('GITHUB_REPOSITORY')}/releases/tag/{tag}",
    )


def formatted_body(release: Release) -> str:
    body = release.body.strip() or "_No release notes provided._"
    source = f"_Source release: {release.html_url}_"
    if "Source release:" in body or release.html_url in body:
        return body
    return f"{body}\n\n{source}"


def codeberg_owner_repo() -> tuple[str, str] | None:
    owner_repo = env("MIRROR_CODEBERG_OWNER_REPO") or env("CODEBERG_REPO")
    if "/" not in owner_repo:
        return None
    owner, repo = owner_repo.split("/", 1)
    return quote(owner, safe=""), quote(repo, safe="")


def github_tag_sha(tag: str) -> str:
    sha = env("GITHUB_TAG_SHA")
    if not sha:
        raise RuntimeError("GITHUB_TAG_SHA is empty; fetch and resolve the tag before syncing releases")
    return sha


def sync_gitlab(action: str, release: Release) -> None:
    token = env("GITLAB_ACCESS_TOKEN") or env("GITLAB_TOKEN")
    project_id = env("GITLAB_PROJECT_ID")
    api_url = env("GITLAB_API_URL", "https://gitlab.com/api/v4").rstrip("/")
    if not token or not project_id:
        print("GitLab release sync skipped: token/project id missing")
        return

    headers = {"PRIVATE-TOKEN": token}
    project = quote(project_id, safe="")
    tag = quote(release.tag, safe="")
    base_url = f"{api_url}/projects/{project}/releases"

    if action == "deleted":
        request_json("DELETE", f"{base_url}/{tag}", headers, ok_statuses=(200, 202, 204, 404))
        print(f"Deleted GitLab release {release.tag}")
        return

    payload = {
        "name": release.name,
        "tag_name": release.tag,
        "description": formatted_body(release),
        "ref": github_tag_sha(release.tag),
    }

    existing = request_json("GET", f"{base_url}/{tag}", headers, ok_statuses=(200, 404))
    if existing:
        commit_id = ((existing.get("commit") or {}).get("id") or "").lower()
        if commit_id and commit_id != github_tag_sha(release.tag).lower():
            request_json("DELETE", f"{base_url}/{tag}", headers, ok_statuses=(200, 202, 204, 404))
            existing = None
            print(f"Deleted stale GitLab release {release.tag}: {commit_id} != {github_tag_sha(release.tag)}")

    if existing:
        request_json(
            "PUT",
            f"{base_url}/{tag}",
            headers,
            {"name": release.name, "description": formatted_body(release)},
        )
        print(f"Updated GitLab release {release.tag}")
    else:
        request_json("POST", base_url, headers, payload)
        print(f"Created GitLab release {release.tag}")


def codeberg_tag_sha(api_url: str, owner: str, repo: str, headers: dict[str, str], tag: str) -> str:
    tag_ref = quote(f"tags/{tag}", safe="/")
    ref = request_json("GET", f"{api_url}/repos/{owner}/{repo}/git/refs/{tag_ref}", headers)
    if isinstance(ref, list):
        ref = ref[0] if ref else {}
    ref_object = (ref or {}).get("object") or {}
    sha = ref_object.get("sha")
    if not sha:
        raise RuntimeError(f"Codeberg tag {tag!r} was not found after mirror sync")
    if ref_object.get("type") == "tag":
        annotated_tag = request_json("GET", f"{api_url}/repos/{owner}/{repo}/git/tags/{sha}", headers)
        sha = ((annotated_tag or {}).get("object") or {}).get("sha")
        if not sha:
            raise RuntimeError(f"Codeberg annotated tag {tag!r} did not include a commit SHA")
    return str(sha)


def sync_codeberg(action: str, release: Release) -> None:
    token = env("CODEBERG_TOKEN")
    owner_repo = codeberg_owner_repo()
    api_url = env("CODEBERG_API_URL", "https://codeberg.org/api/v1").rstrip("/")
    if not token or not owner_repo:
        print("Codeberg release sync skipped: CODEBERG_TOKEN/MIRROR_CODEBERG_OWNER_REPO missing")
        return

    owner, repo = owner_repo
    headers = {"Authorization": f"token {token}"}
    base_url = f"{api_url}/repos/{owner}/{repo}/releases"
    tag_url = f"{base_url}/tags/{quote(release.tag, safe='')}"

    request_json("GET", f"{api_url}/repos/{owner}/{repo}", headers)

    existing = request_json("GET", tag_url, headers, ok_statuses=(200, 404))
    if action == "deleted":
        if existing:
            delete_codeberg_release(base_url, headers, existing)
            print(f"Deleted Codeberg release {release.tag}")
        return

    target_sha = codeberg_tag_sha(api_url, owner, repo, headers, release.tag)
    github_sha = github_tag_sha(release.tag)
    if target_sha.lower() != github_sha.lower():
        if existing:
            delete_codeberg_release(base_url, headers, existing)
            print(f"Deleted stale Codeberg release {release.tag}: {target_sha} != {github_sha}")
        raise RuntimeError(f"Codeberg tag {release.tag!r} is not mirrored to the latest GitHub SHA yet")

    if existing:
        existing_target = str(existing.get("target_commitish") or "").lower()
        if existing_target and existing_target != target_sha.lower():
            delete_codeberg_release(base_url, headers, existing)
            existing = None
            print(f"Deleted stale Codeberg release {release.tag}: {existing_target} != {target_sha}")

    payload = {
        "tag_name": release.tag,
        "target_commitish": target_sha,
        "name": release.name,
        "body": formatted_body(release),
        "draft": release.draft,
        "prerelease": release.prerelease,
    }

    if existing:
        request_json("PATCH", f"{base_url}/{existing['id']}", headers, payload)
        print(f"Updated Codeberg release {release.tag}")
    else:
        request_json("POST", base_url, headers, payload)
        print(f"Created Codeberg release {release.tag}")


def delete_codeberg_release(base_url: str, headers: dict[str, str], release: dict[str, Any]) -> None:
    release_id = release.get("id")
    if not release_id:
        return
    request_json("DELETE", f"{base_url}/{release_id}", headers, ok_statuses=(200, 202, 204, 404))


def main() -> int:
    action, release = load_release()
    sync_gitlab(action, release)
    sync_codeberg(action, release)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Release sync failed: {exc}", file=sys.stderr)
        raise
