from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
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
                raise RuntimeError(f"{method} API returned HTTP {response.status}")
            return json.loads(raw.decode("utf-8")) if raw else None
    except HTTPError as error:
        if error.code not in ok_statuses:
            raise RuntimeError(f"{method} API returned HTTP {error.code}") from None
        return None
    except (URLError, TimeoutError):
        raise RuntimeError(f"{method} API connection failed") from None


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
            raise RuntimeError(f"GitLab release {release.tag!r} aponta para outro commit; nenhuma release foi apagada")

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
        raise RuntimeError(f"Codeberg tag {release.tag!r} is not mirrored to the latest GitHub SHA yet")

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


class ReleaseMirror:
    """Snapshot e compensação conservadora de metadados de uma release."""
    def __init__(self, kind: str, release: Release):
        self.kind = kind
        self.release = release
        if kind == 'gitlab':
            token, project = env('GITLAB_ACCESS_TOKEN') or env('GITLAB_TOKEN'), env('GITLAB_PROJECT_ID')
            if not token or not project:
                raise RuntimeError('GitLab: token ou projeto não configurado')
            api = env('GITLAB_API_URL', 'https://gitlab.com/api/v4').rstrip('/')
            self.base = f'{api}/projects/{quote(project, safe="")}/releases'
            self.url = f'{self.base}/{quote(release.tag, safe="")}'
            self.headers = {'PRIVATE-TOKEN': token}
        else:
            token, owner_repo = env('CODEBERG_TOKEN'), codeberg_owner_repo()
            if not token or not owner_repo:
                raise RuntimeError('Codeberg: token ou repositório não configurado')
            owner, repo = owner_repo
            api = env('CODEBERG_API_URL', 'https://codeberg.org/api/v1').rstrip('/')
            self.api, self.owner, self.repo = api, owner, repo
            self.base = f'{api}/repos/{owner}/{repo}/releases'
            self.url = f'{self.base}/tags/{quote(release.tag, safe="")}'
            self.headers = {'Authorization': f'token {token}'}

    def snapshot(self):
        return request_json('GET', self.url, self.headers, ok_statuses=(200, 404))

    def signature(self, item):
        if item is None:
            return None
        if self.kind == 'gitlab':
            return (item.get('name'), item.get('description'), item.get('released_at'),
                    (item.get('commit') or {}).get('id'), item.get('assets'), item.get('milestones'))
        return (item.get('id'), item.get('name'), item.get('body'), item.get('draft'),
                item.get('prerelease'), item.get('target_commitish'), item.get('assets'))

    def has_assets(self, item):
        if not item:
            return False
        if self.kind == 'gitlab':
            return bool((item.get('assets') or {}).get('links'))
        return bool(item.get('assets'))

    def rollback(self, before, after):
        current = self.snapshot()
        if self.signature(current) != self.signature(after):
            raise RuntimeError(f'{self.kind}: release alterada após sincronização; reversão cancelada')
        if before is None and after is not None:
            if self.has_assets(current):
                raise RuntimeError(f'{self.kind}: release recebeu anexos; exclusão cancelada')
            url = self.url if self.kind == 'gitlab' else f'{self.base}/{current["id"]}'
            request_json('DELETE', url, self.headers, ok_statuses=(200, 202, 204))
        elif before is not None and after is None:
            if self.has_assets(before):
                raise RuntimeError(f'{self.kind}: não é possível restaurar anexos automaticamente')
            if self.kind == 'gitlab':
                tag_url = f'{self.base[:-len("/releases")]}/repository/tags/{quote(self.release.tag, safe="")}'
                tag = request_json('GET', tag_url, self.headers, ok_statuses=(200, 404))
                expected_commit = (before.get('commit') or {}).get('id')
                if not tag or (expected_commit and (tag.get('commit') or {}).get('id') != expected_commit):
                    raise RuntimeError('GitLab: tag ausente ou alterada; recriação da release cancelada')
                payload = {'tag_name': self.release.tag, 'name': before.get('name'),
                           'description': before.get('description'), 'released_at': before.get('released_at'),
                           'ref': (before.get('commit') or {}).get('id')}
                milestones = [m['title'] for m in before.get('milestones') or [] if m.get('title')]
                if milestones:
                    payload['milestones'] = milestones
            else:
                tag_sha = codeberg_tag_sha(self.api, self.owner, self.repo, self.headers, self.release.tag)
                expected = str(before.get('target_commitish') or '')
                if len(expected) == 40 and all(c in '0123456789abcdefABCDEF' for c in expected) and expected.lower() != tag_sha.lower():
                    raise RuntimeError('Codeberg: tag alterada; recriação da release cancelada')
                payload = {key: before.get(key) for key in ('tag_name', 'target_commitish', 'name', 'body', 'draft', 'prerelease')}
            request_json('POST', self.base, self.headers, payload)
        elif before is not None and after is not None:
            if self.kind == 'gitlab':
                request_json('PUT', self.url, self.headers,
                             {'name': before.get('name'), 'description': before.get('description')})
            else:
                payload = {key: before.get(key) for key in ('tag_name', 'target_commitish', 'name', 'body', 'draft', 'prerelease')}
                request_json('PATCH', f'{self.base}/{current["id"]}', self.headers, payload)
        print(f'{self.kind}: metadados anteriores restaurados')


def sync_transaction(action: str, release: Release):
    mirrors = [ReleaseMirror('gitlab', release), ReleaseMirror('codeberg', release)]
    snapshots = [(mirror, mirror.snapshot()) for mirror in mirrors]
    if action == 'deleted':
        for mirror, before in snapshots:
            if mirror.has_assets(before):
                raise RuntimeError(f'{mirror.kind}: exclusão bloqueada; anexos não podem ser restaurados automaticamente')
    completed = []
    current_step = None
    try:
        for mirror, before in snapshots:
            current_step = (mirror, before)
            if mirror.signature(mirror.snapshot()) != mirror.signature(before):
                raise RuntimeError(f'{mirror.kind}: release mudou durante a preparação')
            (sync_gitlab if mirror.kind == 'gitlab' else sync_codeberg)(action, release)
            after = mirror.snapshot()
            completed.append((mirror, before, after))
            current_step = None
    except Exception as error:
        failures = []
        if current_step:
            mirror, before = current_step
            try:
                if mirror.signature(mirror.snapshot()) != mirror.signature(before):
                    failures.append(f'{mirror.kind}: estado da etapa com erro é incerto; revise manualmente')
            except Exception as exc:
                failures.append(f'{mirror.kind}: não foi possível confirmar o estado: {exc}')
        for mirror, before, after in reversed(completed):
            try:
                mirror.rollback(before, after)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError(f'{error}; REVERSÃO INCOMPLETA: ' + '; '.join(failures)) from error
        raise RuntimeError(f'{error}; alterações anteriores revertidas') from error


def main() -> int:
    action, release = load_release()
    sync_transaction(action, release)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Release sync failed: {exc}", file=sys.stderr)
        raise
