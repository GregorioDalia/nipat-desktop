"""Discover and download official releases without installing or executing them.

HTTPS and release metadata establish provenance; hashes detect incomplete or changed
downloads. These checks do not claim that an executable has a code-signing certificate.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import platform as host_platform
import re
import stat
import sys
import tempfile
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from nipat.errors import NipatError


REPOSITORY = "GregorioDalia/nipat-desktop"
API = f"https://api.github.com/repos/{REPOSITORY}"
WEB = f"https://github.com/{REPOSITORY}"
UPDATER_VERSION = 1
PLATFORMS = frozenset({"windows-x86_64", "linux-x86_64"})
MAX_ASSET_SIZE = 2**31 - 1
JSON_LIMIT = 2 * 1024 * 1024
MANIFEST_LIMIT = 128 * 1024
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:(a|b|rc)(0|[1-9][0-9]*))?\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_HOSTS = frozenset({"api.github.com", "github.com", "release-assets.githubusercontent.com",
                    "objects.githubusercontent.com", "github-releases.githubusercontent.com",
                    "github-production-release-asset-2e65be.s3.amazonaws.com"})


class UpdateError(NipatError):
    def __init__(self, message: str, *, status: str = "invalid_metadata"):
        super().__init__(message)
        self.status = status


def version_key(version: str) -> tuple[int, int, int, int, int]:
    """Compare the supported numeric release/a/b/rc versions, without dependencies."""
    match = _VERSION.fullmatch(version) if isinstance(version, str) and len(version) <= 80 else None
    if not match:
        raise UpdateError("Versione NIPAT non riconosciuta.")
    major, minor, patch, phase, number = match.groups()
    return int(major), int(minor), int(patch), {"a": 0, "b": 1, "rc": 2, None: 3}[phase], int(number or 0)


def detect_platform() -> str:
    machine = host_platform.machine().lower()
    if machine not in {"amd64", "x86_64"} or sys.platform not in {"win32", "linux"}:
        raise UpdateError("Gli aggiornamenti richiedono Windows o Linux x86_64.", status="unsupported_platform")
    return "windows-x86_64" if sys.platform == "win32" else "linux-x86_64"


def _installer_name(version: str, platform: str) -> str:
    version_key(version)
    if platform == "windows-x86_64":
        return "NIPAT-Setup.exe"
    if platform == "linux-x86_64":
        debian_version = re.sub(r"(a|b|rc)([0-9]+)$", r"~\1\2", version)
        return f"nipat-desktop_{debian_version}_amd64.deb"
    raise UpdateError("Piattaforma aggiornamenti non supportata.", status="unsupported_platform")


@dataclass(frozen=True)
class UpdateAsset:
    platform: str
    name: str
    size: int
    sha256: str
    url: str


@dataclass(frozen=True)
class UpdateOffer:
    version: str
    release_tag: str
    channel: str
    source_commit: str
    minimum_updater_version: int
    asset: UpdateAsset
    release_notes_url: str

    @property
    def asset_name(self) -> str:
        return self.asset.name

    @property
    def size(self) -> int:
        return self.asset.size

    @property
    def release_url(self) -> str:
        return self.release_notes_url


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    message: str
    offer: UpdateOffer | None = None


def _transport_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == "https" and parts.hostname in _HOSTS
                 and parts.port in {None, 443} and not parts.username and not parts.password
                 and not parts.fragment and not any(char.isspace() or ord(char) == 127 for char in url))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise UpdateError("Download interrotto: indirizzo HTTPS non autorizzato.")


class _SafeRedirectHandler(HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urljoin(req.full_url, newurl)
        _transport_url(destination)
        return super().redirect_request(req, fp, code, msg, headers, destination)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UpdateError("Metadati aggiornamento non validi: chiavi duplicate.")
        result[key] = value
    return result


def _required(condition: bool, message: str) -> None:
    if not condition:
        raise UpdateError(message)


def _validated_asset(data: object, version: str, tag: str) -> UpdateAsset:
    _required(isinstance(data, dict) and data.keys() == {"platform", "name", "size", "sha256", "url"},
              "Descrizione del pacchetto di aggiornamento non valida.")
    platform = data["platform"]
    _required(isinstance(platform, str) and platform in PLATFORMS, "Piattaforma del pacchetto non valida.")
    name = _installer_name(version, platform)
    _required(data["name"] == name, "Nome del pacchetto diverso dalla versione dichiarata.")
    _required(type(data["size"]) is int and 0 < data["size"] <= MAX_ASSET_SIZE,
              "Dimensione del pacchetto non valida.")
    _required(isinstance(data["sha256"], str) and bool(_HASH.fullmatch(data["sha256"])),
              "Checksum del pacchetto non valido.")
    expected = f"{WEB}/releases/download/{tag}/{name}"
    _required(data["url"] == expected, "Il pacchetto non appartiene alla release NIPAT dichiarata.")
    return UpdateAsset(platform, name, data["size"], data["sha256"], expected)


def _validate_offer(offer: UpdateOffer) -> None:
    _required(isinstance(offer, UpdateOffer), "Offerta di aggiornamento non valida.")
    version_key(offer.version)
    _required(offer.release_tag == "v" + offer.version, "Tag aggiornamento non valido.")
    _required(isinstance(offer.channel, str) and offer.channel in {"stable", "testing"}, "Canale aggiornamento non valido.")
    _required(isinstance(offer.source_commit, str) and bool(_COMMIT.fullmatch(offer.source_commit)),
              "Commit aggiornamento non valido.")
    _required(type(offer.minimum_updater_version) is int and 0 < offer.minimum_updater_version <= UPDATER_VERSION,
              "Questa release richiede un programma di aggiornamento piu' recente.")
    _required(offer.release_notes_url == f"{WEB}/releases/tag/{offer.release_tag}",
              "Indirizzo delle note di release non valido.")
    _required(isinstance(offer.asset, UpdateAsset), "Pacchetto aggiornamento non valido.")
    _validated_asset(vars(offer.asset), offer.version, offer.release_tag)


class UpdateClient:
    """Public GitHub reads only; no account, telemetry or scientific inputs are sent."""

    def __init__(self, *, opener=None, timeout: float = 5.0, check_budget: float = 15.0,
                 max_pages: int = 3, max_manifests: int = 10, clock: Callable[[], float] = time.monotonic):
        self._open = opener or build_opener(_SafeRedirectHandler()).open
        self.timeout, self.check_budget = timeout, check_budget
        self.max_pages, self.max_manifests, self.clock = max_pages, max_manifests, clock

    def _request(self, url: str, *, deadline: float | None = None):
        _transport_url(url)
        timeout = self.timeout
        if deadline is not None:
            timeout = min(timeout, deadline - self.clock())
            if timeout <= 0:
                raise UpdateError("Controllo aggiornamenti incompleto: tempo disponibile esaurito.", status="incomplete")
        request = Request(url, headers={"User-Agent": "NIPAT-Updater/1", "Accept": "application/vnd.github+json"
                                       if url.startswith(API + "/") else "application/octet-stream",
                                       "Accept-Encoding": "identity", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            response = self._open(request, timeout=timeout)
            try:
                _transport_url(response.geturl())
            except BaseException:
                response.close()
                raise
            return response
        except HTTPError as exc:
            headers = exc.headers or {}
            limited = exc.code == 429 or (exc.code == 403 and
                      (headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After")))
            if limited:
                raise UpdateError("GitHub ha limitato temporaneamente le richieste. Riprovare piu' tardi.",
                                  status="rate_limited") from exc
            raise UpdateError(f"GitHub non ha reso disponibile il file richiesto (HTTP {exc.code}). Riprovare piu' tardi.",
                              status="offline") from exc
        except (URLError, OSError, TimeoutError, HTTPException) as exc:
            raise UpdateError("Impossibile contattare GitHub. Verificare la connessione e riprovare.", status="offline") from exc

    def _json(self, url: str, *, deadline: float, limit: int = JSON_LIMIT):
        try:
            with self._request(url, deadline=deadline) as response:
                chunks = []
                size = 0
                read = getattr(response, "read1", response.read)
                while True:
                    if self.clock() > deadline:
                        raise UpdateError("Controllo aggiornamenti incompleto: tempo disponibile esaurito.", status="incomplete")
                    chunk = read(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    _required(size <= limit, "Metadati di aggiornamento troppo grandi.")
                content = b"".join(chunks)
            _required(len(content) <= limit, "Metadati di aggiornamento troppo grandi.")
            if self.clock() > deadline:
                raise UpdateError("Controllo aggiornamenti incompleto: tempo disponibile esaurito.", status="incomplete")
            return json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
        except UpdateError:
            raise
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise UpdateError("Metadati di aggiornamento non leggibili.") from exc
        except (OSError, URLError, TimeoutError, HTTPException) as exc:
            raise UpdateError("La connessione a GitHub e' stata interrotta. Riprovare.", status="offline") from exc

    def _releases(self, deadline: float) -> list[dict]:
        releases = []
        for page in range(1, self.max_pages + 1):
            batch = self._json(f"{API}/releases?per_page=100&page={page}", deadline=deadline)
            _required(isinstance(batch, list) and len(batch) <= 100 and all(isinstance(item, dict) for item in batch),
                      "Elenco delle release non valido.")
            releases.extend(batch)
            if len(batch) < 100:
                return releases
        raise UpdateError("Controllo aggiornamenti incompleto: elenco delle release troppo esteso.", status="incomplete")

    def _verify_source(self, tag: str, source: str, deadline: float) -> None:
        record = self._json(f"{API}/git/ref/tags/{tag}", deadline=deadline)
        _required(isinstance(record, dict) and record.get("ref") == f"refs/tags/{tag}",
                  "Il tag della release non e' verificabile.")
        for _ in range(4):
            obj = record.get("object") if isinstance(record, dict) else None
            _required(isinstance(obj, dict) and isinstance(obj.get("sha"), str)
                      and bool(_COMMIT.fullmatch(obj["sha"])), "Riferimento sorgente della release non valido.")
            if obj.get("type") == "commit":
                _required(obj["sha"] == source, "Il tag della release non corrisponde ai sorgenti dichiarati.")
                return
            _required(obj.get("type") == "tag", "Il tag della release non identifica un commit.")
            record = self._json(f"{API}/git/tags/{obj['sha']}", deadline=deadline)
        raise UpdateError("Il tag della release contiene troppi riferimenti indiretti.")

    def _manifest(self, release: dict, version: str, platform: str, deadline: float) -> UpdateOffer | None:
        tag = "v" + version
        assets = release.get("assets")
        _required(isinstance(assets, list) and all(isinstance(asset, dict) for asset in assets),
                  "Elenco dei pacchetti della release non valido.")
        descriptors = [asset for asset in assets if asset.get("name") == "update-manifest.json"]
        if not descriptors:
            return None
        _required(len(descriptors) == 1, "Manifest di aggiornamento duplicato.")
        descriptor = descriptors[0]
        url = f"{WEB}/releases/download/{tag}/update-manifest.json"
        _required(descriptor.get("browser_download_url") == url and descriptor.get("state") == "uploaded"
                  and type(descriptor.get("size")) is int and 0 < descriptor["size"] <= MANIFEST_LIMIT,
                  "Manifest di aggiornamento non disponibile o estraneo alla release.")
        data = self._json(url, deadline=deadline, limit=MANIFEST_LIMIT)
        required = {"schema_version", "product", "version", "release_tag", "channel", "source_commit",
                    "minimum_updater_version", "assets", "release_notes_url"}
        _required(isinstance(data, dict) and data.keys() == required and type(data["schema_version"]) is int
                  and data["schema_version"] == 1 and data["product"] == "nipat-desktop",
                  "Formato del manifest di aggiornamento non supportato.")
        _required(data["version"] == version and data["release_tag"] == tag, "Versione del manifest diversa dalla release.")
        expected_channel = "testing" if release["prerelease"] else "stable"
        _required(data["channel"] == expected_channel, "Canale del manifest diverso dalla release GitHub.")
        _required(expected_channel == "testing" or version_key(version)[3] == 3,
                  "Una versione preliminare non puo' appartenere al canale stabile.")
        source = data["source_commit"]
        _required(isinstance(source, str) and bool(_COMMIT.fullmatch(source)), "Commit sorgente non valido.")
        minimum = data["minimum_updater_version"]
        _required(type(minimum) is int and minimum > 0, "Versione minima dell'updater non valida.")
        _required(data["release_notes_url"] == f"{WEB}/releases/tag/{tag}", "Note di release non appartenenti al progetto.")
        _required(isinstance(data["assets"], list) and 0 < len(data["assets"]) <= len(PLATFORMS),
                  "Pacchetti nel manifest non validi.")
        decoded = [_validated_asset(asset, version, tag) for asset in data["assets"]]
        _required(len({asset.platform for asset in decoded}) == len(decoded), "Piattaforma duplicata nel manifest.")
        for asset in decoded:
            published = [item for item in assets if item.get("name") == asset.name]
            _required(len(published) == 1 and published[0].get("state") == "uploaded"
                      and published[0].get("browser_download_url") == asset.url
                      and type(published[0].get("size")) is int and published[0]["size"] == asset.size,
                      "Il pacchetto pubblicato non corrisponde al manifest.")
            if published[0].get("digest") is not None:
                _required(published[0]["digest"] == "sha256:" + asset.sha256,
                          "Il checksum pubblicato da GitHub non corrisponde al manifest.")
        selected = next((asset for asset in decoded if asset.platform == platform), None)
        if selected is None:
            return None
        if minimum > UPDATER_VERSION:
            raise UpdateError("Una nuova release richiede un updater piu' recente. Consultare le release ufficiali NIPAT.",
                              status="unsupported_updater")
        self._verify_source(tag, source, deadline)
        return UpdateOffer(version, tag, expected_channel, source, minimum, selected, data["release_notes_url"])

    def check(self, current_version: str, channel: str, platform: str) -> UpdateCheck:
        try:
            current = version_key(current_version)
            _required(isinstance(channel, str) and channel in {"stable", "testing"}, "Canale aggiornamenti non valido.")
            _required(isinstance(platform, str) and platform in PLATFORMS, "Piattaforma aggiornamenti non supportata.")
            deadline = self.clock() + self.check_budget
            candidates = []
            had_managed_release = False
            for release in self._releases(deadline):
                if release.get("draft") is True or not release.get("published_at"):
                    continue
                _required(release.get("draft") is False and type(release.get("prerelease")) is bool,
                          "Stato della release GitHub non valido.")
                tag = release.get("tag_name")
                if not isinstance(tag, str) or not tag.startswith("v") or not _VERSION.fullmatch(tag[1:]):
                    continue
                if channel == "stable" and release["prerelease"]:
                    continue
                _required(release.get("html_url") == f"{WEB}/releases/tag/{tag}", "Release appartenente a un altro progetto.")
                has_manifest = isinstance(release.get("assets"), list) and any(
                    isinstance(asset, dict) and asset.get("name") == "update-manifest.json" for asset in release["assets"])
                if not has_manifest:
                    continue
                had_managed_release = True
                if version_key(tag[1:]) > current:
                    candidates.append((version_key(tag[1:]), tag[1:], release))
            candidates.sort(key=lambda item: item[0], reverse=True)
            for index, (_, version, release) in enumerate(candidates):
                if index >= self.max_manifests:
                    raise UpdateError("Controllo aggiornamenti incompleto: troppe release da verificare.", status="incomplete")
                offer = self._manifest(release, version, platform, deadline)
                if offer:
                    return UpdateCheck("available", f"NIPAT {offer.version} disponibile nel canale {offer.channel}.", offer)
            if had_managed_release and not candidates:
                return UpdateCheck("up_to_date", "Non risultano versioni piu' recenti nel canale selezionato.")
            return UpdateCheck("no_eligible_release", "Nessuna release con aggiornamento compatibile per questo sistema nel canale selezionato.")
        except UpdateError as exc:
            return UpdateCheck(exc.status, str(exc))

    def download(self, offer: UpdateOffer, directory: Path,
                 progress: Callable[[int, int], None] | None = None) -> Path:
        """Return only a complete verified package; a failed download preserves old cache."""
        _validate_offer(offer)
        destination_dir = _safe_directory(directory)
        destination = destination_dir / offer.asset.name
        _regular_or_missing(destination)
        if destination.is_file() and _file_matches(destination, offer.asset):
            if progress:
                progress(offer.asset.size, offer.asset.size)
            return destination
        part: Path | None = None
        try:
            with self._request(offer.asset.url) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    _required(isinstance(content_length, str) and len(content_length) <= 20
                              and bool(re.fullmatch(r"[0-9]+", content_length)) and int(content_length) == offer.asset.size,
                              "Dimensione del download diversa dal manifest.")
                with tempfile.NamedTemporaryFile(mode="wb", prefix=offer.asset.name + ".", suffix=".part",
                                                 dir=destination_dir, delete=False) as stream:
                    part = Path(stream.name)
                    digest = hashlib.sha256()
                    count = 0
                    if progress:
                        progress(0, offer.asset.size)
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        _required(count <= offer.asset.size, "Il download supera la dimensione dichiarata.")
                        stream.write(chunk)
                        digest.update(chunk)
                        if progress:
                            progress(count, offer.asset.size)
                    _required(count == offer.asset.size, "Download incompleto: dimensione non corrispondente.")
                    _required(digest.hexdigest() == offer.asset.sha256, "Checksum del download non corrispondente. Il file non verra' utilizzato.")
                    stream.flush()
                    os.fsync(stream.fileno())
            _safe_directory(destination_dir)
            _regular_or_missing(destination)
            os.replace(part, destination)
            part = None
            return destination
        except UpdateError:
            raise
        except (OSError, URLError, TimeoutError, HTTPException) as exc:
            raise UpdateError("Download interrotto o file non scrivibile. Nessun aggiornamento e' stato avviato.", status="offline") from exc
        finally:
            if part is not None:
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    pass


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _safe_directory(directory: Path) -> Path:
    path = Path(directory).expanduser().absolute()
    _required(".." not in path.parts, "La cartella aggiornamenti non puo' contenere attraversamenti '..'.")
    try:
        for parent in [*reversed(path.parents), path]:
            _required(not _is_link(parent), "La cartella aggiornamenti non puo' attraversare collegamenti o junction.")
            _required(not parent.exists() or parent.is_dir(), "La destinazione aggiornamenti non e' una cartella.")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for parent in [*reversed(path.parents), path]:
            _required(not _is_link(parent), "La cartella aggiornamenti e' stata sostituita con un collegamento.")
        return path
    except OSError as exc:
        raise UpdateError("Cartella degli aggiornamenti non disponibile o non scrivibile.") from exc


def _regular_or_missing(path: Path) -> None:
    _required(not _is_link(path), "Il file dell'aggiornamento non puo' essere un collegamento.")
    _required(not path.exists() or path.is_file(), "La destinazione del pacchetto non e' un file regolare.")


def _file_matches(path: Path, asset: UpdateAsset) -> bool:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            _required(stat.S_ISREG(info.st_mode), "Il pacchetto salvato non e' un file regolare.")
            if info.st_size != asset.size:
                return False
            return hashlib.file_digest(stream, "sha256").hexdigest() == asset.sha256
    except OSError as exc:
        raise UpdateError("Impossibile verificare il pacchetto gia' scaricato.") from exc
