"""Check this repo before anything in it is published.

    python tools/check_pages.py                              every file in the repo
    python tools/check_pages.py <folder>                     one page folder
    python tools/check_pages.py <folder> --changed-against origin/main
                                                             one page folder, and that the
                                                             branch touches nothing else

The exit code is 0 when nothing fails and 1 when anything does. A line marked LOOK never
changes the exit code: it is something a person has to look at, and the owner sees it when
asked to approve the page.

The repo is a closed world. Every file is either one of the repo's own, named below, or sits
in a page folder. Anything else fails, because everything here is served to the public.

Standard library only. The rules are decisions/ADR-0001-published-pages.md; this file is
how they are kept.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import html
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

SITE_HOST = "drakontas.github.io"
SITE_PATH = "/pages/"

# A page folder is <YYYY-MM>-<slug>: lower-case words joined by single hyphens.
# \Z and not $: a $ also matches before a newline at the end of a name.
PAGE_FOLDER = re.compile(r"\A(\d{4})-(0[1-9]|1[0-2])-[a-z0-9]+(?:-[a-z0-9]+)*\Z")

# The repo's own files. Nothing else may sit outside a page folder.
ROOT_FILES = frozenset(
    {"README.md", "index.html", "404.html", ".nojekyll", ".gitattributes", ".gitignore", "LICENSE"}
)
REPO_FILES = (
    re.compile(r"\Atools/[a-z_]+\.py\Z"),
    re.compile(r"\Atests/test_[a-z_]+\.py\Z"),
    re.compile(r"\Atests/made_up\.json\Z"),
    re.compile(r"\Adecisions/ADR-\d{4}-[a-z0-9-]+\.md\Z"),
    re.compile(r"\A\.github/workflows/[a-z-]+\.yml\Z"),
    re.compile(r"\A\.github/CODEOWNERS\Z"),
)
REPO_FOLDERS = frozenset({"tools", "tests", "decisions", ".github"})
# The check and its tests hold private-looking text on purpose: it is what they look for.
# Every such value must be named in the list of made-up values, so a real one cannot
# arrive in a test unnoticed.
HOLDS_EXAMPLES = frozenset({"tools", "tests"})
MADE_UP = "tests/made_up.json"
NEVER_PUBLISHED = frozenset({".git", "__pycache__"})   # git ignores both

PAGE_KEYS = frozenset({"title", "created", "session", "summary", "external_resources", "allow"})
REQUIRED_FIELDS = ("title", "created", "session", "summary")
CREATED = re.compile(r"\A\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\Z")

HTML_SUFFIXES = frozenset({".html", ".htm", ".xhtml", ".xht", ".shtml"})
SCRIPT_SUFFIXES = frozenset({".js", ".mjs"})
ALLOWED_SUFFIXES = HTML_SUFFIXES | SCRIPT_SUFFIXES | frozenset({
    ".svg", ".css", ".json", ".geojson", ".txt", ".csv", ".tsv", ".md", ".xml", ".vtt",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".pdf",
    ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm", ".mp3", ".wav", ".ogg",
})
MUST_BE_TEXT = HTML_SUFFIXES | SCRIPT_SUFFIXES | frozenset({".svg", ".css", ".json"})
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_REPO_FILE_BYTES = 1024 * 1024

ALLOWED_EMAILS = re.compile(r"\A(?:[^@\s]+@users\.noreply\.github\.com|noreply@github\.com)\Z", re.I)
# In a commit message, the address of a tool that helped write the commit is allowed too.
MESSAGE_EMAILS = re.compile(
    r"\A(?:[^@\s]+@users\.noreply\.github\.com|noreply@(?:github|anthropic)\.com)\Z", re.I)

# --------------------------------------------------------------------------------------
# Text that only means something on the owner's own network or machine.
# Each entry: what it is, whether it is specific enough to trust in a binary file (where
# short patterns match random bytes), and the pattern. A path may be written with its
# backslashes doubled, as JSON and most code write them, so each pattern takes both.
#
# A pattern takes the whole of what it finds and never its first step alone: a path to
# the end of the path, an address with its port and everything after it. What page.json
# allows is compared with the whole of what was found, so allowing one path or one
# address does not allow every other that begins the same way.
# --------------------------------------------------------------------------------------
_REST = r"[^\s\"'`<>|\x00-\x1f\x7f-\x9f]{0,400}"
# A folder's name may hold spaces. A path goes on through as many as four words with a
# space before each, when the last of them runs into another step of the path, as in a
# path through "Program Files" or through "Old Shows 2024".
_WORD = r"[^\s\"'`<>|/\\:\x00-\x1f\x7f-\x9f]{1,60}"
_PATH = _REST + r"(?:(?: " + _WORD + r"){1,4}[\\/]" + _REST + r"){0,8}"
_SEP = r"(?:\\{1,2}|/)"
# What may stand before a host and after it in an address: http://user@ and :8080/files/x.
_BEFORE_A_HOST = r"(?:\b[A-Za-z][A-Za-z0-9+.-]{0,20}://(?:[^/\s\"'<>@]{0,80}@)?)?"
_AFTER_A_HOST = r"(?::\d{1,5})?(?:[/?#]" + _REST + r")?"
# What follows the slash that closes a pattern written in code, such as /a|b:/gi, or
# /a|b:/.test(x). It is not the start of a path.
_AFTER_A_PATTERN = r"(?![dgimsuvy]{0,8}(?:[\s,;)\]}]|$|\.[A-Za-z]+\())"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_IP_START = r"(?<![\d.])"          # keeps 110.1.2.3 out of the match
_IP_END = r"(?![\d]|\.\d)"         # keeps 10.1.2.100.5 out of the match
_PRIVATE_SUFFIX = r"(?:local|lan|internal|localdomain|home|corp|home\.arpa)"
PRIVATE = (
    ("a private network address", True, re.compile(
        rf"{_BEFORE_A_HOST}{_IP_START}(?:10\.{_OCTET}|192\.168|172\.(?:1[6-9]|2\d|3[01])|169\.254"
        rf"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))\.{_OCTET}\.{_OCTET}{_IP_END}{_AFTER_A_HOST}")),
    ("a loopback address", True, re.compile(
        rf"{_BEFORE_A_HOST}{_IP_START}127\.\d{{1,3}}\.\d{{1,3}}\.\d{{1,3}}{_IP_END}{_AFTER_A_HOST}")),
    ("a private IPv6 address", False, re.compile(
        rf"(?:{_BEFORE_A_HOST}\[)?"
        r"(?<![0-9a-f:])(?:::1(?![0-9a-f:.])|fe80:(?::[0-9a-f]{0,4})+"
        r"|f[cd][0-9a-f]{2}(?::[0-9a-f]{0,4}){2,})"
        rf"(?:\]{_AFTER_A_HOST}|/{_REST})?", re.I)),
    ("localhost", False, re.compile(
        rf"{_BEFORE_A_HOST}(?<![\w.-])localhost(?![\w-]){_AFTER_A_HOST}", re.I)),
    ("a file: or smb: link", True, re.compile(rf"\b(?:file|smb):/{_PATH}", re.I)),
    # Two backslashes, a host, one backslash and a share; or the same with each backslash
    # doubled, as code writes it. Two and then two is neither: it is how code writes a run
    # of escapes, as in a pattern that lists the kinds of white space.
    ("a Windows share path", True, re.compile(
        rf"(?<!\\)(?:\\{{2}}[A-Za-z0-9][\w.-]*\\(?!\\)|\\{{4}}[A-Za-z0-9][\w.-]*\\{{2}}(?!\\))"
        rf"[\w$.-]{_PATH}")),
    ("a share path", False, re.compile(rf"(?<![:\w/.])//[A-Za-z0-9-]+/[\w$.-]{_PATH}")),
    ("a drive path", False, re.compile(rf"(?<![A-Za-z0-9])[A-Za-z]:\\{{1,2}}[\w.~$%-]{_PATH}")),
    ("a drive path", False, re.compile(
        rf"(?<![A-Za-z0-9\\])[A-Za-z]:/{_AFTER_A_PATTERN}[\w.~$%-]{_PATH}")),
    ("a drive path", False, re.compile(rf"(?<![\w./:<])/[a-z]/[\w.-]+/{_PATH}")),
    ("a user folder", True, re.compile(rf"(?<![\w.]){_SEP}(?:Users|home){_SEP}[\w.-]{_PATH}")),
    ("an environment variable path", True, re.compile(
        r"%(?:USERPROFILE|APPDATA|LOCALAPPDATA|HOMEPATH|HOMEDRIVE|TEMP|TMP|USERNAME"
        rf"|COMPUTERNAME|PROGRAMDATA)%{_PATH}", re.I)),
    # The name ends where a name must: at anything a host name cannot hold. A comma, a
    # semicolon, a bracket or a row of dots after it ends it as well as a space does. What
    # follows is not the rest of a name, and not the "name:password@" that stands before
    # a host.
    ("a host name that only works on a private network", False, re.compile(
        rf"\b(?:https?|wss?|ftp)://(?:[^/\s\"'<>@]{{0,80}}@)?"
        rf"(?:[A-Za-z0-9_-]+|[A-Za-z0-9._-]+\.{_PRIVATE_SUFFIX})\.?(?::\d{{1,5}})?"
        rf"(?:[/?#\\]{_REST}|\.*(?![A-Za-z0-9._@%-]|:[^/\s\"'<>@]{{0,80}}@))",
        re.I)),
)
# Marks that end a sentence or close a bracket. They follow a path and are not part of it.
_TRAILING = ".,;:!?)]}"

# Things a person must look at. They are LOOK lines because a public office's own phone
# number or address is a fair thing to publish, and only a reader can tell the difference.
# An address ends in letters, which keeps a version such as chart.js@4.4.1 out.
# Each pattern starts only at the front of a run of letters, so that a long run with no
# address in it is read once and not once for every letter. The name has no limit on its
# length: a limit would let an address past with a long enough name.
_NAME = r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+"
EMAIL = re.compile(_NAME + r"@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,}\b")
# An address written to dodge a harvester: jo [at] example [dot] com.
# It may be wrapped over a line or indented, so the white space in it has no limit.
SPELLED_EMAIL = re.compile(
    _NAME + r"\s*[\[(]\s*at\s*[\])]\s*[A-Za-z0-9-]{1,63}"
    r"(?:\s*[\[(]\s*dot\s*[\])]\s*[A-Za-z0-9-]{1,63}){1,8}", re.I)
PHONE = re.compile(
    r"(?<![\d.])(?:\+?1[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\d])"
    r"|(?<![\d.+\w])\+\d{1,3}(?:[ .-]?\d{2,4}){2,4}(?![\d])")

# --------------------------------------------------------------------------------------
# Addresses. An address is resolved the way a browser would resolve it, and judged after.
# --------------------------------------------------------------------------------------
INSIDE, OUTSIDE, EXTERNAL, INLINE, FORBIDDEN = "inside", "outside", "external", "inline", "forbidden"
INLINE_SCHEMES = frozenset({"data", "blob", "mailto", "tel"})
SCHEME = re.compile(r"^([a-z][a-z0-9+.-]*):", re.I)
# Namespace names. They look like addresses and are never fetched.
INERT_PREFIXES = ("http://www.w3.org/", "https://www.w3.org/")

URL_LITERAL = re.compile(r"(?:https?|wss?|ftp):/{0,2}[^\s\"'`<>()\\]+", re.I)
QUOTED_RELATIVE_HOST = re.compile(r"[\"'`(]\s*(//[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+[^\s\"'`<>()\\]*)")
# A path in quotes, in code: '../other/data.json', "./img/a.png", '/pages/other/'.
# The steps up are taken all at once and never given back one by one, so a long run of
# them with no closing quote is read once.
QUOTED_PATH = re.compile(
    r"[\"'`]((?:\.{1,2}/)+(?!\.{1,2}/)[^\s\"'`<>()\\]*|/[^\s\"'`<>()\\/*][^\s\"'`<>()\\]*)[\"'`]")
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")\s]+)", re.I)
CSS_IMPORT = re.compile(r"@import\s*(?:url\(\s*)?['\"]([^'\"]+)['\"]", re.I)
CSS_IMAGE_SET = re.compile(r"image-set\(([^;{}]*)", re.I)
CSS_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")
CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\r\n\f]?|(.))", re.S)

# Attributes that hold an address, on any element.
URL_ATTRS = frozenset({
    "href", "xlink:href", "src", "poster", "data", "action", "formaction", "background",
    "cite", "manifest", "longdesc", "codebase", "archive", "icon", "profile", "classid",
})
LIST_ATTRS = {"srcset": ",", "imagesrcset": ",", "ping": None}
# Addresses a reader follows by choice. Everything else is fetched to draw the page.
FOLLOWED = frozenset({("a", "href"), ("area", "href"), ("form", "action"),
                      ("button", "formaction"), ("input", "formaction")})
INERT_RELS = frozenset({"canonical", "author", "license", "help", "prev", "next", "me", "alternate"})
# Elements whose content a browser does not treat as live markup in the document head.
INERT = frozenset({"template", "noscript", "title", "textarea", "xmp", "svg", "math", "script",
                   "style", "iframe", "noembed", "noframes", "plaintext"})


def clean_url(url: str) -> str:
    """Undo what a browser undoes before it reads an address."""
    url = re.sub(r"[\x00-\x20\x7f]", "", html.unescape(url))
    url = url.replace("\\", "/")
    return re.sub(r"%(2e|2f|5c)", lambda m: {"2e": ".", "2f": "/", "5c": "/"}[m.group(1).lower()],
                  url, flags=re.I)


def classify(url: str, folder: str) -> tuple[str, str]:
    """Say where an address leads, and give the address it resolves to."""
    cleaned = clean_url(url)
    found = SCHEME.match(cleaned)
    scheme = found.group(1).lower() if found else ""
    if scheme in INLINE_SCHEMES:
        return INLINE, cleaned
    if scheme and scheme not in ("http", "https"):
        return FORBIDDEN, cleaned
    base = f"https://{SITE_HOST}{SITE_PATH}{folder}/" if folder else f"https://{SITE_HOST}{SITE_PATH}"
    try:
        resolved = urljoin(base, cleaned)
        parts = urlsplit(resolved)
        host = (parts.hostname or "").lower().rstrip(".")     # example.org. is example.org
        has_login = bool(parts.username or parts.password)
    except ValueError:
        return FORBIDDEN, cleaned
    if has_login:
        return FORBIDDEN, resolved
    if host == SITE_HOST:
        path = unquote(parts.path)
        if folder and path.startswith(f"{SITE_PATH}{folder}/") and ".." not in path.split("/"):
            return INSIDE, resolved
        return OUTSIDE, resolved
    return EXTERNAL, resolved


def is_declared(resolved: str, declared: list[str]) -> bool:
    """True when an outside address falls under one that page.json lists."""
    try:
        got = urlsplit(resolved)
        got_port = got.port
    except ValueError:
        return False
    if ".." in unquote(got.path).replace("\\", "/").split("/"):
        return False                        # a path that climbs may leave what was declared
    for entry in declared:
        want = urlsplit(entry)
        if got.scheme != "https" or (got.hostname or "").lower() != (want.hostname or "").lower():
            continue
        if got_port != want.port:
            continue
        prefix = want.path or "/"
        if got.path == prefix or got.path.startswith(prefix if prefix.endswith("/") else prefix + "/"):
            return True
    return False


def decode_css(css: str) -> str:
    def one(m: re.Match) -> str:
        if m.group(1):
            code = int(m.group(1), 16)
            return chr(code) if 0 < code < 0x110000 else ""
        return m.group(2)
    return CSS_ESCAPE.sub(one, css)


def css_addresses(css: str) -> list[str]:
    css = decode_css(css)
    found = CSS_URL.findall(css) + CSS_IMPORT.findall(css)
    for body in CSS_IMAGE_SET.findall(css):
        found.extend(CSS_QUOTED.findall(body))
    found.extend(code_addresses(css))
    return found


def code_addresses(code: str) -> list[str]:
    """Every outside address written out in a piece of code."""
    code = code.replace("\\/", "/")         # JSON may write a slash with a backslash before it
    found = [m.group(0) for m in URL_LITERAL.finditer(code)]
    found.extend(QUOTED_RELATIVE_HOST.findall(code))
    return [f.rstrip(".,;") for f in found if not f.lower().startswith(INERT_PREFIXES)]


def code_paths(code: str) -> list[str]:
    """Every path written in quotes in a piece of code: fetch('../other/data.json').

    The check cannot tell a path the code loads from one it only holds as text, so these
    are judged apart: page.json may allow one. A path that begins with a slash is taken
    only when it reads as a path to a file or a folder, which leaves '/month' alone.
    """
    code = code.replace("\\/", "/")
    return [path for path in QUOTED_PATH.findall(code)
            if not path.startswith("/") or path.lower().startswith("/pages")
            or "/" in path[1:] or "." in path]


class _Page(HTMLParser):
    """Collect what one file asks the browser to fetch, and whether it says noindex."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.noindex = False
        self.indexable: list[str] = []            # robots tags that do not say noindex
        self.fetched: list[str] = []              # fetched to draw the page
        self.named: list[str] = []                # paths in quotes in code
        self.followed: list[str] = []             # followed only when a reader chooses
        self.forbidden: list[str] = []            # never allowed, whatever they hold
        self._in_head = False
        self._seen_body = False
        self._inert: list[str] = []

    def _tag(self, tag: str, attrs: list[tuple[str, str | None]], closed: bool) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "head" and not self._seen_body:
            self._in_head = True
        elif tag == "body":
            self._in_head, self._seen_body = False, True
        if tag == "meta":
            self._meta(a)
        if tag == "base":
            self.forbidden.append("a <base> element, which moves every address in the file")
        if "srcdoc" in a:
            self.forbidden.append("a srcdoc attribute, which holds a second page the check cannot read")
        rels = set(a.get("rel", "").lower().split())
        followed_link = tag == "link" and bool(rels) and rels <= INERT_RELS
        for name, value in a.items():
            if name.startswith("xmlns") or not value:
                continue
            if name in LIST_ATTRS:
                parts = value.split(LIST_ATTRS[name])
                self.fetched.extend(p.split()[0] for p in parts if p.split())
            elif name in URL_ATTRS:
                if (tag, name) in FOLLOWED or followed_link or name == "cite":
                    self.followed.append(value)
                else:
                    self.fetched.append(value)
            elif name == "style":
                self.fetched.extend(css_addresses(value))
            else:
                self.fetched.extend(code_addresses(value))
                self.named.extend(code_paths(value))
        if tag in INERT and not closed:
            self._inert.append(tag)

    def _meta(self, a: dict[str, str]) -> None:
        if a.get("http-equiv", "").strip().lower() == "refresh":
            self.forbidden.append("a refresh that sends the reader to another address")
        if a.get("name", "").strip().lower() != "robots":
            return
        words = {w.strip().lower() for w in a.get("content", "").split(",")}
        if self._inert:
            return                                  # a browser reads this one as text
        if not words & {"noindex", "none"}:
            self.indexable.append(a.get("content", ""))
        elif self._in_head:
            self.noindex = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs, closed=True)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        if tag in self._inert:
            while self._inert and self._inert.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        inside = self._inert[-1] if self._inert else ""
        if inside == "style":
            self.fetched.extend(css_addresses(data))
        elif inside == "script":
            self.fetched.extend(code_addresses(data))
            self.named.extend(code_paths(data))


# --------------------------------------------------------------------------------------
# Embedded files, such as an image written into the page as base64. The letters of base64
# include "/" and "+", so a run of them matches path patterns by chance. Each embedded
# file is taken out of the text, and then read on its own for what it holds.
# --------------------------------------------------------------------------------------
# An embedded file goes on over a line break only into a full line of base64, or into a
# last, shorter line that the closing quote or bracket of the address follows. Words
# after it on the same line are never part of it.
DATA_URI = re.compile(
    r"(data:[^,\s\"'`()<>]{0,200};base64,)"
    r"([A-Za-z0-9+/]*(?:[ \t]*\r?\n[ \t]*[A-Za-z0-9+/]{60,})*"
    r"(?:[ \t]*\r?\n[ \t]*[A-Za-z0-9+/]*={0,2}(?=\s*[\"'`)]))?={0,2})", re.I)
# Lines of base64, as a mail program or a certificate wraps them. A last, shorter line
# counts only when it ends in "=": without that it cannot be told from a path. The full
# lines are all of one length, so a path stuck to the front of one shows.
# It starts only at the front of a run, so one long word with no line break in it is read
# once and not once for every letter.
WRAPPED = re.compile(
    r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{60,}\r?\n[ \t]*){2,}(?:[A-Za-z0-9+/]*={1,2})?")
PAYLOAD = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
EMBEDDED = ", inside a file written into this one"
DEEPEST = 3
TOO_DEEP = ("a file written into another, more than three deep, which the check does not read",
            "base64")


def take_payloads(text: str) -> tuple[str, list[str]]:
    """The text with each embedded file taken out, and the embedded files."""
    taken: list[str] = []

    def data_uri(m: re.Match) -> str:
        taken.append(m.group(2))
        return f"{m.group(1)} "

    def wrapped(m: re.Match) -> str:
        full = [line.strip() for line in m.group(0).splitlines()]
        if full and "=" in full[-1]:
            full = full[:-1]
        if len({len(line) for line in full if line}) > 1:
            return m.group(0)               # lines of different lengths: read it as text
        taken.append(m.group(0))
        return " "

    def run(m: re.Match) -> str:
        taken.append(m.group(0))
        return " "

    text = DATA_URI.sub(data_uri, text)
    text = WRAPPED.sub(wrapped, text)
    return PAYLOAD.sub(run, text), taken


def strip_payloads(text: str) -> str:
    return take_payloads(text)[0]


def decode_payload(payload: str) -> bytes | None:
    letters = re.sub(r"[^A-Za-z0-9+/]", "", payload)
    try:
        return base64.b64decode(letters + "=" * (-len(letters) % 4))
    except (binascii.Error, ValueError):
        return None


def readings(text: str, binary: bool = False, depth: int = 0):
    """The text without its embedded files, then each embedded file, as (text, binary, embedded)."""
    if binary:
        yield text, True, depth > 0
        return
    stripped, payloads = take_payloads(text)
    yield stripped, False, depth > 0
    if depth >= DEEPEST:
        if payloads:
            yield None, False, True         # something is here, and it is not read
        return
    for payload in payloads:
        raw = decode_payload(payload)
        if raw is None:
            continue
        try:
            inner = raw.decode("utf-8")
        except UnicodeDecodeError:
            yield raw.decode("latin-1"), True, True
        else:
            yield from readings(inner, False, depth + 1)


def as_a_browser_reads(text: str, binary: bool) -> list[str]:
    """The text as written, and again with its character references and % codes decoded."""
    if binary:
        return [text]
    decoded = html.unescape(unquote(text))
    return [text] if decoded == text else [text, decoded]


def is_page_folder(name: str) -> bool:
    return PAGE_FOLDER.match(name) is not None


def without_what_follows(found: str) -> str:
    """Take off the marks that end a sentence. A bracket that was opened inside stays."""
    opens = {")": "(", "]": "[", "}": "{"}
    while found and found[-1] in _TRAILING:
        last = found[-1]
        if last in opens and found.count(opens[last]) >= found.count(last):
            break
        found = found[:-1]
    return found


def private_in(text: str, binary: bool) -> list[tuple[str, str]]:
    hits = []
    for what, binary_safe, pattern in PRIVATE:
        if binary and not binary_safe:
            continue
        for m in pattern.finditer(text):
            found = m.group(0)
            if binary:                      # in a binary file a path ends where the text does
                found = re.match(r"[\x20-\x7e]*", found).group(0)
            found = without_what_follows(found)
            hits.append((m.start(), m.start() + len(found), what, found))
    # A path inside a longer path is the same finding. Keep the longer one, and keep one
    # where two patterns find the same text.
    hits.sort(key=lambda h: (h[0], -h[1]))
    kept, reach = [], -1
    for hit in hits:
        if hit[1] <= reach:
            continue
        kept.append(hit)
        reach = hit[1]
    return [(what, found) for _, _, what, found in kept]


def find_private(text: str, binary: bool = False) -> list[tuple[str, str]]:
    """Private addresses and paths in a text, and in every file written into it."""
    seen: dict[tuple[str, str], None] = {}
    for reading, is_binary, embedded in readings(text, binary):
        if reading is None:
            seen.setdefault(TOO_DEEP, None)
            continue
        for version in as_a_browser_reads(reading, is_binary):
            for what, found in private_in(version, is_binary):
                seen.setdefault((what + EMBEDDED if embedded else what, found), None)
    return list(seen)


def find_contacts(text: str) -> list[tuple[str, str]]:
    found: dict[tuple[str, str], None] = {}
    for reading, is_binary, _ in readings(text):
        if is_binary or reading is None:
            continue
        for version in as_a_browser_reads(reading, False):
            for m in EMAIL.finditer(version):
                found.setdefault(("email address", m.group(0)), None)
            for m in SPELLED_EMAIL.finditer(version):
                found.setdefault(("email address", m.group(0)), None)
            for m in PHONE.finditer(version):
                found.setdefault(("phone number", m.group(0)), None)
    return sorted(found)


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self._said: set[tuple[bool, str]] = set()   # so that a long report is not slow

    def fail(self, where: str, what: str) -> None:
        line = f"{where}: {what}"
        if (True, line) not in self._said:
            self._said.add((True, line))
            self.failures.append(line)

    def warn(self, where: str, what: str) -> None:
        line = f"{where}: {what}"
        if (False, line) not in self._said:
            self._said.add((False, line))
            self.warnings.append(line)


def read_text(path: Path) -> str | None:
    """The file as text, or None when it is not text."""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def declared_problem(entry: str) -> str:
    try:
        parts = urlsplit(entry)
        host = parts.hostname or ""
        login = parts.username or parts.password
        parts.port
    except ValueError:
        return "cannot be read as an address"
    if parts.scheme != "https":
        return "must begin https://"
    if "." not in host:
        return "must name a full host, such as cdn.example.org"
    if login or parts.query or parts.fragment:
        return "must be a plain address: no login, no ? and no #"
    return ""


def check_metadata(folder: Path, report: Report) -> tuple[list[str], list[str]]:
    """Check page.json. Return the outside addresses it declares and the text it allows."""
    where = f"{folder.name}/page.json"
    path = folder / "page.json"
    if "page.json" not in os.listdir(folder) or not path.is_file():
        report.fail(where, "missing. Every page folder carries one")
        return [], []
    text = read_text(path)
    try:
        data = json.loads(text if text is not None else "")
    except json.JSONDecodeError as err:
        report.fail(where, f"cannot be read as JSON ({err})")
        return [], []
    if not isinstance(data, dict):
        report.fail(where, "must be a JSON object")
        return [], []
    for key in sorted(set(data) - PAGE_KEYS):
        report.fail(where, f'"{key}" is not a field this repo knows. The file is public, '
                           "so it holds nothing beyond what is asked for")
    for field in REQUIRED_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            report.fail(where, f'"{field}" is required and must be text')
    created = data.get("created")
    if isinstance(created, str) and created.strip():
        if not CREATED.match(created):
            report.fail(where, f'"created" must be YYYY-MM-DD, not "{created}"')
        elif created[:7] != folder.name[:7]:
            report.fail(where, f'"created" is {created} but the folder is dated {folder.name[:7]}')
    lists: dict[str, list[str]] = {}
    for key in ("external_resources", "allow"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            report.fail(where, f'"{key}" must be a list of text entries')
            value = []
        lists[key] = value
    declared = []
    for entry in lists["external_resources"]:
        problem = declared_problem(entry)
        if problem:
            report.fail(where, f'external resource "{entry}" {problem}')
        else:
            declared.append(entry)
            report.warn(where, f'the page may load from "{entry}"')
    for entry in lists["allow"]:
        report.warn(where, f'allows the text "{entry}", which the check would otherwise refuse')
    return declared, lists["allow"]


def as_json_writes(entries: list[str]) -> list[str]:
    """Each entry, and the entry as a JSON file holds it, with its backslashes doubled."""
    forms = list(entries)
    for entry in entries:
        for form in (json.dumps(entry)[1:-1], json.dumps(entry, ensure_ascii=False)[1:-1]):
            if form not in forms:
                forms.append(form)
    return forms


def scan_text(where: str, text: str, allow: list[str], report: Report, binary: bool = False) -> None:
    for what, found in find_private(text, binary):
        # the whole of what was found, never its start; and never a file left unread
        if found in allow and (what, found) != TOO_DEEP:
            continue
        report.fail(where, f'holds {what}, "{found}". It means nothing to a reader, '
                           "and it says something about where the page was made")
    if binary:
        return
    for what, found in find_contacts(text):
        report.warn(where, f'{what} "{found}". Publish only if it is a public office\'s')


def judge_addresses(where: str, folder: str, fetched: list[str], followed: list[str],
                    declared: list[str], report: Report,
                    named: list[str] | None = None, allow: list[str] | None = None) -> None:
    for url in named or []:
        kind, _ = classify(url, folder)
        if kind != INSIDE and url not in (allow or []):
            report.fail(where, f'names "{url}" in its code, which leads outside its own folder. '
                               'If the page never loads it, list it under "allow" in page.json')
    for url in fetched:
        kind, resolved = classify(url, folder)
        if kind == OUTSIDE:
            report.fail(where, f'loads "{url}" from outside its own folder')
        elif kind == FORBIDDEN:
            report.fail(where, f'loads "{url}", which is not a kind of address a page may use')
        elif kind == EXTERNAL and not is_declared(resolved, declared):
            report.fail(where, f'names "{url}" on another site, and page.json does not '
                               'list it under "external_resources"')
    for url in followed:
        kind, _ = classify(url, folder)
        if kind == OUTSIDE:
            report.fail(where, f'links to "{url}", outside its own folder')
        elif kind == FORBIDDEN:
            report.fail(where, f'links to "{url}", which is not a kind of address a page may use')


def check_markup(where: str, folder: str, text: str, suffix: str, declared: list[str],
                 report: Report, allow: list[str] | None = None) -> _Page | None:
    fetched: list[str] = []
    followed: list[str] = []
    named: list[str] = []
    page = None
    if suffix in HTML_SUFFIXES or suffix == ".svg":
        page = _Page()
        try:
            page.feed(text)
            page.close()
        except Exception as err:               # a parser that gives up is not a pass
            report.fail(where, f"cannot be read as markup ({err})")
            return None
        if suffix in HTML_SUFFIXES:
            if not page.noindex:
                report.fail(where, 'has no <meta name="robots" content="noindex"> inside <head>. '
                                   "Write the <head> and </head> tags out, with the tag between them")
            for content in page.indexable:
                report.fail(where, f'has a robots tag, "{content}", that does not say noindex')
        for what in page.forbidden:
            report.fail(where, f"has {what}")
        fetched, followed, named = page.fetched, page.followed, page.named
    elif suffix == ".css":
        fetched = css_addresses(text)
    elif suffix in SCRIPT_SUFFIXES:
        fetched, named = code_addresses(text), code_paths(text)
    judge_addresses(where, folder, fetched, followed, declared, report, named, allow)
    return page


def walk(top: Path, report: Report, root: Path, in_a_page: bool = False):
    """Every file under a folder. Links are reported and never followed."""
    for current, dirs, files in os.walk(top, followlinks=False):
        here = Path(current)
        for name in list(dirs):
            path = here / name
            if in_a_page and (name in NEVER_PUBLISHED or name.startswith(".")):
                report.fail(path.relative_to(root).as_posix(), "is not a kind of folder a page may hold")
                dirs.remove(name)
            elif name in NEVER_PUBLISHED:
                dirs.remove(name)
            elif path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                report.fail(path.relative_to(root).as_posix(), "is a link. A page holds its own files")
                dirs.remove(name)
        for name in sorted(files):
            path = here / name
            if path.is_symlink():
                report.fail(path.relative_to(root).as_posix(), "is a link. A page holds its own files")
            else:
                yield path


def check_folder(folder: Path, report: Report) -> None:
    root = folder.parent
    declared, allow = check_metadata(folder, report)
    if "index.html" not in os.listdir(folder):
        report.fail(folder.name, "has no index.html, in lower case, so its address shows nothing")
    in_page_json = as_json_writes(allow)
    for path in walk(folder, report, root, in_a_page=True):
        where = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if path.name.startswith(".") or suffix not in ALLOWED_SUFFIXES:
            report.fail(where, "is not a kind of file a page may hold")
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            report.fail(where, f"is {size // (1024 * 1024)} MB. The limit is 25 MB a file")
            continue
        text = read_text(path)
        if text is None:
            if suffix in MUST_BE_TEXT:
                report.fail(where, "cannot be read as UTF-8 text")
            else:
                scan_text(where, path.read_bytes().decode("latin-1"), allow, report, binary=True)
            continue
        scan_text(where, text, in_page_json if where == f"{folder.name}/page.json" else allow, report)
        check_markup(where, folder.name, text, suffix, declared, report, allow)


def read_repo_file(path: Path, where: str, report: Report) -> str | None:
    size = path.stat().st_size
    if size > MAX_REPO_FILE_BYTES:
        report.fail(where, f"is {size // 1024} KB. The limit for one of the repo's own files is 1 MB")
        return None
    text = read_text(path)
    if text is None:
        report.fail(where, "cannot be read as UTF-8 text")
    return text


def read_made_up(root: Path, report: Report) -> list[str]:
    """The made-up values the check and its tests may hold."""
    path = root / MADE_UP
    if not path.is_file() or path.is_symlink():
        return []
    try:
        data = json.loads(read_text(path) or "")
    except json.JSONDecodeError as err:
        report.fail(MADE_UP, f"cannot be read as JSON ({err})")
        return []
    if not isinstance(data, list) or not all(isinstance(v, str) and v for v in data):
        report.fail(MADE_UP, "must be a list of text entries")
        return []
    return data


def check_example_file(path: Path, where: str, made_up: list[str], report: Report) -> None:
    """A file of the check or its tests: every private-looking value in it is a listed one."""
    text = read_repo_file(path, where, report)
    if text is None:
        return
    for what, found in find_private(text) + find_contacts(text):
        if found not in made_up or (what, found) == TOO_DEEP:
            report.fail(where, f'holds {what}, "{found}", which {MADE_UP} does not list. '
                               "If it is real, take it out and use a made-up one. The list "
                               "is for a value that belongs to no one, and the owner reads "
                               "each new entry before the branch is pushed")


def check_repo_file(path: Path, where: str, made_up: list[str], report: Report) -> None:
    """One of the repo's own files. It is served, and nobody approves it as a page."""
    text = read_repo_file(path, where, report)
    if text is None:
        return
    for what, found in find_private(text):
        report.fail(where, f'holds {what}, "{found}". It means nothing to a reader, '
                           "and it says something about where the file was made")
    for what, found in find_contacts(text):
        if found not in made_up:
            report.fail(where, f'holds the {what} "{found}", which {MADE_UP} does not list. '
                               "The repo's own files hold no real contact details")
    suffix = path.suffix.lower()
    if suffix in HTML_SUFFIXES:
        page = check_markup(where, "", text, suffix, [], report)
        if page is not None and (page.fetched or page.followed or page.named):
            report.fail(where, "links to or loads something. The root pages name no page, "
                               "because the site is unlisted")


def show_new_made_up(root: Path, base: str | None, report: Report) -> None:
    """Each made-up value the base did not list is shown, for a person to read.

    With nothing to compare with, every value is new.
    """
    before = set(made_up_before(root, base)) if base else set()
    than = f"which {base[:12]} did not" if base else "and there is no main to compare it with"
    for value in read_made_up(root, Report()):
        if value not in before:
            report.warn(MADE_UP, f'lists "{value}" as made up, {than}. '
                                 "Show it to the owner before the branch is pushed")


def where_main_is(root: Path) -> str | None:
    """The commit to compare the list with when nobody named one.

    Never the branch's own last commit: what the branch has committed is what is new.
    """
    for ref in ("origin/main", "main"):
        try:
            done = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                                   f"{ref}^{{commit}}"], capture_output=True)
        except OSError:
            return None
        if done.returncode == 0:
            return ref
    return None


def check_repo_files(root: Path, report: Report, compared: bool = False) -> None:
    """Everything outside the page folders: a closed list, and nothing private in it."""
    made_up = read_made_up(root, report)
    if not compared:                        # with --changed-against it is shown there
        show_new_made_up(root, where_main_is(root), report)
    for path in sorted(root.iterdir()):
        name = path.name
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            report.fail(name, "is a link")
        elif name in NEVER_PUBLISHED or (is_page_folder(name) and path.is_dir()):
            continue
        elif path.is_dir():
            if name not in REPO_FOLDERS:
                report.fail(name, "is not named <YYYY-MM>-<slug>, in lower case with single "
                                  "hyphens, and is not one of the repo's own folders")
                continue
            for inner in walk(path, report, root):
                where = inner.relative_to(root).as_posix()
                if not any(p.match(where) for p in REPO_FILES):
                    report.fail(where, "is not one of the repo's own files, and is not in a page folder")
                elif where == MADE_UP:
                    continue                # read above. Every value in it is a listed one
                elif name in HOLDS_EXAMPLES:
                    check_example_file(inner, where, made_up, report)
                else:
                    check_repo_file(inner, where, made_up, report)
        elif name not in ROOT_FILES:
            report.fail(name, "is not one of the repo's own files, and is not in a page folder")
        else:
            check_repo_file(path, name, made_up, report)


def made_up_before(root: Path, base: str) -> list[str]:
    """The list of made-up values as the base holds it. Empty when the base has none."""
    done = subprocess.run(["git", "-C", str(root), "show", f"{base}:{MADE_UP}"], capture_output=True)
    try:
        data = json.loads(done.stdout.decode("utf-8-sig")) if done.returncode == 0 else []
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    return [v for v in data if isinstance(v, str)] if isinstance(data, list) else []


def git(root: Path, *args: str) -> list[str]:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    return [p for p in done.stdout.decode("utf-8", "replace").split("\0") if p]


def check_messages(messages: list[str], report: Report) -> None:
    """Commit messages are public, and they are read like any other text."""
    for message in messages:
        for what, found in find_private(message):
            report.fail("branch", f'has a commit message that holds {what}, "{found}". '
                                  "Commit messages are public")
        for what, found in find_contacts(message):
            if what == "phone number":
                report.warn("branch", f'has a commit message that holds the {what} "{found}"')
            elif not MESSAGE_EMAILS.match(found):
                report.fail("branch", f'has a commit message that holds the {what} "{found}". '
                                      "Commit messages are public")


def check_changes(root: Path, ref: str, only: list[str], report: Report) -> None:
    """A branch touches one page folder, or the repo's own files, and never both."""
    try:
        base = git(root, "merge-base", ref, "HEAD")[0].strip()
        changed = set(git(root, "diff", "--name-only", "--no-renames", "-z", base, "HEAD"))
        for entry in git(root, "status", "--porcelain", "--no-renames", "-z", "--untracked-files=all"):
            changed.add(entry[3:])
        emails = set(git(root, "log", "-z", "--format=%ae%x00%ce", f"{base}..HEAD"))
        messages = git(root, "log", "-z", "--format=%B", f"{base}..HEAD")
    except (subprocess.CalledProcessError, IndexError, OSError) as err:
        report.fail("git", f"cannot compare this branch with {ref} ({err}). "
                           "Without that, what the branch publishes is unknown")
        return
    check_messages(messages, report)
    for path in sorted(changed):
        if NEVER_PUBLISHED & set(path.split("/")):
            report.fail("branch", f'touches "{path}". Git leaves such a file out unless it is '
                                  "forced in, and once in, it is served")
    if MADE_UP in changed:
        show_new_made_up(root, base, report)
    pages = sorted({p.split("/")[0] for p in changed if is_page_folder(p.split("/")[0])})
    others = sorted(p for p in changed if not is_page_folder(p.split("/")[0]))
    if len(pages) > 1:
        report.fail("branch", f"touches {len(pages)} page folders ({', '.join(pages)}). One page to a branch")
    if pages and others:
        for path in others:
            report.fail("branch", f'touches "{path}" as well as the page {pages[0]}. '
                                  "Add the page folder alone: git add <folder>")
    for name in only:
        if pages and name.strip("/\\") not in pages:
            report.fail("branch", f"the page asked about is {name}, but the branch touches {pages[0]}")
    for email in sorted(emails):
        if not ALLOWED_EMAILS.match(email.strip()):
            report.fail("branch", "has a commit made under an address that is not a GitHub "
                                  "no-reply address. Commits here are public")


def check_repo(root: Path, only: list[str] | None = None, changed_against: str | None = None) -> Report:
    report = Report()
    if only:
        for name in only:
            name = name.strip("/\\")
            if not is_page_folder(name):
                report.fail(name, "is not named <YYYY-MM>-<slug>, in lower case with single hyphens")
            elif name not in os.listdir(root) or not (root / name).is_dir():
                report.fail(name, "is not a folder here")
            else:
                check_folder(root / name, report)
    else:
        check_repo_files(root, report, compared=bool(changed_against))
        for path in sorted(root.iterdir()):
            if path.is_dir() and not path.is_symlink() and is_page_folder(path.name):
                check_folder(path, report)
    if changed_against:
        check_changes(root, changed_against, only or [], report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check this repo before anything in it is published.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--changed-against", metavar="REF",
                        help="also check what this branch changes, compared with REF")
    parser.add_argument("folders", nargs="*", help="page folders to check; default is the whole repo")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):          # a name in another alphabet prints as written
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = check_repo(args.root.resolve(), args.folders, args.changed_against)
    for line in report.warnings:
        print(f"LOOK  {line}")
    for line in report.failures:
        print(f"FAIL  {line}")
    verdict = "FAILED" if report.failures else ("NEEDS A LOOK" if report.warnings else "OK")
    print(f"RESULT: {verdict} - {len(report.failures)} failing, {len(report.warnings)} to look at")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
