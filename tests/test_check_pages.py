"""Edge cases for tools/check_pages.py.  Run:  python -m unittest discover -s tests

Every value here is made up. Addresses come from the ranges kept for examples, and no
name, place or number belongs to anyone.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import check_pages as cp  # noqa: E402

NOINDEX = '<meta name="robots" content="noindex">'
GOOD_META = {
    "title": "A page",
    "created": "2026-09-28",
    "session": "0a1b2c3d",
    "summary": "What it is.",
}
PAGE = "2026-09-sample"


def page(body: str = "", head: str = "") -> str:
    return f"<!doctype html><html><head>{NOINDEX}{head}</head><body>{body}</body></html>"


class Repo:
    """A throwaway repo root holding one page folder."""

    def __init__(self, html: str | None = None, meta: dict | str | None = None,
                 extra: dict[str, str | bytes] | None = None,
                 root: dict[str, str | bytes] | None = None, name: str = PAGE) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.folder = self.root / name
        self.folder.mkdir()
        self.write(f"{name}/index.html", page() if html is None else html)
        if meta != "absent":
            self.write(f"{name}/page.json",
                       meta if isinstance(meta, str) else json.dumps(GOOD_META if meta is None else meta))
        for rel, content in (extra or {}).items():
            self.write(f"{name}/{rel}", content)
        for rel, content in (root or {}).items():
            self.write(rel, content)

    def write(self, rel: str, content: str | bytes) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))

    def check(self, only: list[str] | None = None, changed_against: str | None = None) -> cp.Report:
        return cp.check_repo(self.root, only, changed_against)

    def close(self) -> None:
        self._tmp.cleanup()


class Case(unittest.TestCase):
    def run_repo(self, **kw) -> cp.Report:
        only = kw.pop("only", None)
        repo = Repo(**kw)
        self.addCleanup(repo.close)
        return repo.check(only)

    def assertFails(self, report: cp.Report, where: str, what: str, note: object = "") -> None:
        hits = [f for f in report.failures if f.startswith(where) and what in f]
        self.assertTrue(hits, f"{note!r}: wanted a failure at {where!r} saying {what!r}, "
                              f"got {report.failures}")

    def assertClean(self, report: cp.Report, note: object = "") -> None:
        self.assertEqual(report.failures, [], note)


class FolderNames(Case):
    def test_accepted(self):
        for name in ("2026-09-sample", "2026-12-a-four-word-slug", "2027-01-a", "2026-10-q3",
                     "2026-09-28-dated"):
            self.assertTrue(cp.is_page_folder(name), name)

    def test_refused(self):
        for name in ("sample", "2026-9-sample", "2026-13-sample", "2026-00-sample", "2026-09",
                     "2026-09-", "2026-09-Sample", "2026-09-sam_ple", "2026-09-a--b", "2026-09-a-",
                     "26-09-sample", "2026-09-sample/", "2026-09-sample ", "2026-09-sample\n"):
            self.assertFalse(cp.is_page_folder(name), repr(name))

    def test_stray_top_level_folder_fails(self):
        report = self.run_repo(root={"drafts/x.txt": "x"})
        self.assertFails(report, "drafts", "not named")

    def test_naming_a_folder_cannot_reach_outside_the_repo(self):
        repo = Repo()
        self.addCleanup(repo.close)
        for name in ("..", "../x", "2026-09-sample/../..", "/", "nothing-here", "2026-09-absent"):
            self.assertTrue(repo.check([name]).failures, name)
        self.assertClean(repo.check([PAGE]))


class PrivateText(Case):
    def found(self, text: str, binary: bool = False) -> list[str]:
        return [hit for _, hit in cp.find_private(text, binary)]

    def test_caught(self):
        for text in (
            "http://10.1.2.3:8080/files/x", "see 192.168.1.4.", "172.16.0.1", "172.31.255.255",
            "10.0.0.1", "169.254.1.1", "100.64.0.1", "100.127.255.254",
            "http://127.0.0.1:8000", "http://localhost:3000/", "run it on localhost",
            "http://[::1]:8000/", "fe80::1", "[fd12:3456::1]", "fc00:0:0:1::2",
            "file:///C:/x.pdf", "file:/C:/x.pdf", "smb://host/share",
            r"\\10.1.2.3\share\x", r"\\fileserver\share", "//fileserver/share/x.pdf",
            r"C:\Users\someone\file", "c:/users/someone/file", r"C:\work\client\notes.txt",
            r"D:\Work\x.pdf", "/c/Users/someone/x", "/c/work/project/", "/home/someone/x",
            "/Users/someone/x", r"%USERPROFILE%\x", "%appdata%/x",
            "http://fileserver/", "http://fileserver:5000/x", "https://box.local/", "http://box.lan/x",
            "http://box.home.arpa/", "https://intranet.corp/", "http://3232235777/",
            "10&#46;1&#46;2&#46;3", "http://10%2E1%2E2%2E3:8080/", "&#92;&#92;fileserver&#92;share",
            # the same paths with their backslashes doubled, as JSON and code write them
            r"C:\\work\\client", r"\\\\fileserver\\share", r"C:\\Users\\someone",
        ):
            self.assertTrue(self.found(text), text)

    def test_left_alone(self):
        for text in (
            "110.1.2.3", "10.1.2.100.5", "172.15.0.1", "172.32.0.1", "192.169.1.1", "8.8.8.8",
            "100.63.0.1", "100.128.0.1", "169.253.1.1", "1.10.0.0.1", "section 10.1",
            "localhost-like", "mylocalhost", "profile://x", "https://example.org/Users/guide",
            "https://example.org/home/page", "https://example.org/a/b/c/", "a\\\\b",
            "https://example.org/", "https://www.home.example.org/", "https://local.example.org/",
            "ratio 3:/4", "https://example.org//double/slash", "12:30", "std::vector", "face::1a",
            "and/or", "</a></b>", "time 10:15:30", "#fc0", "color: #fd1234",
            # a pattern written in code closes with a slash, and is not a path
            "x.replace(/a|b:/g, '')", "if (/a|b:/.test(x)) {}", "x.split(/a|b:/)",
            r"x.split(/\s:/u)", "x.match(/a|b:/gi);",
            # a run of escapes, as code writes them with each backslash doubled
            r'"[\\x20\\t\\r\\n\\f]"', r'"\\r\\n\\f"', r"/[\\\x00-\x1F\x7F]/gu",
            # a letter that ends a longer word is not a drive
            r"key:\dir", "app:/def/x", r"x.replace(/\s:/g, 1)",
        ):
            self.assertEqual(self.found(text), [], text)

    def test_a_path_is_found_whole(self):
        for text, want in (
            (r"see C:\work\client\notes.txt.", [r"C:\work\client\notes.txt"]),
            (r"(kept in C:\work\client)", [r"C:\work\client"]),
            (r"C:\Users\someone\file", [r"C:\Users\someone\file"]),
            ("c:/users/someone/file, and more", ["c:/users/someone/file"]),
            ("/c/work/project/notes.txt", ["/c/work/project/notes.txt"]),
            ("/home/someone/x/y", ["/home/someone/x/y"]),
            (r"\\fileserver\share\deep\er", [r"\\fileserver\share\deep\er"]),
            ("//fileserver/share/x.pdf", ["//fileserver/share/x.pdf"]),
            ("file:///C:/x.pdf", ["file:///C:/x.pdf"]),
            (r"%USERPROFILE%\notes\x", [r"%USERPROFILE%\notes\x"]),
            (r'"C:\\work\\client"', [r"C:\\work\\client"]),
            (r"\\10.1.2.3\share\x", [r"\\10.1.2.3\share\x"]),
        ):
            self.assertEqual(self.found(text), want, text)

    def test_an_address_is_found_whole(self):
        for text, want in (
            ("see 192.168.1.4.", ["192.168.1.4"]),
            ("http://10.1.2.3:8080/files/x", ["http://10.1.2.3:8080/files/x"]),
            ("at 10.1.2.3:8080/files/x, as before", ["10.1.2.3:8080/files/x"]),
            ("https://someone@10.1.2.3/x?y=1#z", ["https://someone@10.1.2.3/x?y=1#z"]),
            ("http://127.0.0.1:8000/admin/", ["http://127.0.0.1:8000/admin/"]),
            ("http://localhost:3000/private/client/", ["http://localhost:3000/private/client/"]),
            ("run it on localhost:3000/private/client", ["localhost:3000/private/client"]),
            ("run it on localhost", ["localhost"]),
            ("http://fileserver/share/client/notes.docx", ["http://fileserver/share/client/notes.docx"]),
            ("https://box.local:8443/a/b?c", ["https://box.local:8443/a/b?c"]),
            ("http://[fd12:3456::1]:8080/files/x", ["http://[fd12:3456::1]:8080/files/x"]),
            ("fe80::1/64", ["fe80::1/64"]),
        ):
            self.assertEqual(self.found(text), want, text)

    def test_a_path_goes_on_through_a_space_in_a_folder_s_name(self):
        for text, want in (
            (r"C:\Users\some one\Documents\client\notes.txt", None),
            (r"C:\Program Files\Tool Box\bin\tool.exe", None),
            ("/home/some one/work/notes.txt", None),
            (r"\\fileserver\share\Old Shows\book.pdf", None),
            ("file:///C:/Users/some one/x.pdf", None),
            (r"C:\work\x and C:\work\y", [r"C:\work\x", r"C:\work\y"]),
            (r"C:\work\x and then more", [r"C:\work\x"]),
            ("/c/work/project/ https://example.org/x", ["/c/work/project/"]),
            (r"C:\work\x see D:\Work\y", [r"C:\work\x", r"D:\Work\y"]),
        ):
            self.assertEqual(self.found(text), [text] if want is None else want, text)

    def test_a_folder_s_name_may_hold_several_spaces(self):
        for text in (
            r"C:\Program Files (x86)\ClientCo\license.key",
            r"C:\Users\someone\OneDrive - Example Ltd\Clients\x.docx",
            r"\\fileserver\share\Old Shows 2024\book.pdf",
            "/home/someone/My Client Files/notes.txt",
        ):
            self.assertEqual(self.found(text), [text], text)
            self.assertEqual(self.found(f"<p>Kept at {text}</p>"), [text], text)

    def test_a_host_name_ends_at_any_mark(self):
        for text, want in (
            ("The scripts are on http://fileserver, as always.", "http://fileserver"),
            ("nas,http://intranet.corp,notes", "http://intranet.corp"),
            ("see http://box.local; it is the NAS", "http://box.local"),
            ("(http://fileserver)", "http://fileserver"),
            ("[http://fileserver]", "http://fileserver"),
            ("{http://fileserver}", "http://fileserver"),
            ("http://fileserver!", "http://fileserver"),
            ("http://fileserver:, then", "http://fileserver"),
            ("http://fileserver:5000, then", "http://fileserver:5000"),
            (r"http://fileserver\share", r"http://fileserver\share"),
            ("http://file_server, then", "http://file_server"),
            ("http://fileserver", "http://fileserver"),
            ("Browse to http://fileserver... then", "http://fileserver"),
            ("http://box.local.. x", "http://box.local"),
            ("http://fileserver.", "http://fileserver"),
        ):
            self.assertEqual(self.found(text), [want], text)

    def test_a_public_host_name_is_not_a_private_one(self):
        for text in ("https://example.com, fine", "https://cdn.example.org;", "(https://example.org)",
                     "https://example.org:8443, then", "https://someone:word@example.org/x",
                     "https://someone:8080@example.org/x", "https://someone@example.org, then",
                     "https://example.corp.example.org, then", "https://my_cdn.example.org/x",
                     "https://example.com...", "https://example.com.. then"):
            self.assertEqual(self.found(text), [], text)

    def test_the_marks_after_a_path_are_not_part_of_it(self):
        for text, want in (
            (r"(see C:\work\x)", r"C:\work\x"),
            (r"C:\work\x (old)\y.", r"C:\work\x (old)\y"),
            ("http://[fd12:3456::1]", "http://[fd12:3456::1]"),
            (r"C:\work\x].", r"C:\work\x"),
        ):
            self.assertEqual(self.found(text), [want], text)
        for text, want in (("a (b)", "a (b)"), ("a (b).", "a (b)"), ("a b)", "a b"),
                           ("a [b]]", "a [b]"), ("a {b}.;", "a {b}"), ("a.,;:!?", "a"), ("", "")):
            self.assertEqual(cp.without_what_follows(text), want, text)

    def test_a_host_name_with_a_closing_dot(self):
        for text in ("http://fileserver./x", "https://box.local./"):
            self.assertTrue(self.found(text), text)
        self.assertEqual(cp.classify("https://drakontas.github.io./pages/", PAGE)[0], cp.OUTSIDE)

    def test_embedded_base64_is_not_mistaken_for_a_path(self):
        blob = ("QUJD+//ab/cd/ef+/x/yz/" * 40)
        self.assertEqual(self.found(f'<img src="data:image/png;base64,{blob}">'), [])
        self.assertTrue(self.found(f'{blob} then 10.1.2.3'))

    def test_base64_broken_into_lines_is_not_mistaken_for_a_path(self):
        line = "//ab/cdEF+/x/yz/" + "A" * 60
        lines = "\n".join([line] * 6)
        for text in (f'<img src="data:image/png;base64,{lines}">',
                     f"<img src='data:image/png;base64,{lines}\n  QUJD'>",
                     f"url(data:font/woff2;base64,{lines})",
                     f"-----BEGIN-----\n{lines}\nQUJDRA==\n-----END-----"):
            self.assertEqual(self.found(text), [], text[:60])

    def test_text_after_an_embedded_file_is_still_read(self):
        line = "QUJD" * 19
        lines = "\n".join([line] * 4)
        for text in ("data:image/png;base64,QUJD then 10.1.2.3",
                     "<p>Written as data:text/plain;base64,SGVsbG8 and kept in /home/someone/work/notes</p>",
                     "<p>data:text/plain;base64,SGVsbG8 /c/work/project/notes</p>",
                     f"data:image/png;base64,{line}\n/home/someone/work/notes and more",
                     f"/home/someone/x/{line}\n{line}\n{line}\n",
                     "/c/work/" + "a" * 70 + "\nand more",
                     f'<img src="data:image/png;base64,{lines}"> 10.1.2.3',
                     f"data:image/png;base64,{lines}\n10.1.2.3",
                     f"{lines}\n10.1.2.3",
                     f"{lines}\nC:/work/client/x"):
            self.assertTrue(self.found(text), text[:60])

    def test_an_embedded_file_is_read_for_what_it_holds(self):
        inner = base64.b64encode(b"<svg><!-- made at http://10.1.2.3:8080/files/x --></svg>").decode()
        hits = cp.find_private(f'<img src="data:image/svg+xml;base64,{inner}">')
        self.assertEqual([hit for _, hit in hits], ["http://10.1.2.3:8080/files/x"])
        self.assertIn("inside a file written into this one", hits[0][0])
        # a file inside a file inside the page
        outer = base64.b64encode(f'<img src="data:image/svg+xml;base64,{inner}">'.encode()).decode()
        self.assertTrue(self.found(f"url(data:text/html;base64,{outer})"))
        # a long run that names no kind of file, and a binary file that holds a path
        self.assertTrue(self.found(base64.b64encode(b"x" * 200 + b" 10.1.2.3 ").decode()))
        packed = base64.b64encode(b"\xff\xfe /Author (C:\\Users\\someone\\x)").decode()
        self.assertTrue(self.found(f'<img src="data:application/pdf;base64,{packed}">'))
        report = self.run_repo(html=page(f'<img src="data:image/svg+xml;base64,{inner}">'))
        self.assertFails(report, f"{PAGE}/index.html", "a private network address")

    def test_a_file_too_deep_to_read_may_not_be_allowed(self):
        self.assertEqual(cp.DEEPEST, 3)         # the message says three
        text = "kept at /home/someone/x"
        for _ in range(cp.DEEPEST + 1):
            text = "data:text/plain;base64," + base64.b64encode(text.encode()).decode()
        report = self.run_repo(html=page(f'<a href="{text}">x</a>'),
                               meta={**GOOD_META, "allow": [cp.TOO_DEEP[1]]})
        self.assertFails(report, f"{PAGE}/index.html", "does not read")

    def test_a_file_too_deep_to_read_fails(self):
        text = "kept at /home/someone/x"
        for depth in range(1, 6):
            text = "data:text/plain;base64," + base64.b64encode(text.encode()).decode()
            hits = cp.find_private(f'<a href="{text}">x</a>')
            self.assertTrue(hits, depth)
            if depth > cp.DEEPEST:
                self.assertEqual(hits, [cp.TOO_DEEP], depth)
            else:
                self.assertEqual([hit for _, hit in hits], ["/home/someone/x"], depth)

    def test_binary_files_are_read_for_the_specific_patterns_only(self):
        self.assertTrue(self.found("x/Author (C:\\Users\\someone\\x)", binary=True))
        self.assertTrue(self.found("\x00\x01 10.1.2.3 \xff", binary=True))
        self.assertEqual(self.found("\x00a:/b\x01//ab/cd localhost", binary=True), [])

    def test_private_text_fails_in_any_file_of_a_page(self):
        for rel in ("data.json", "notes.txt", "table.tsv", "more/app.js", "style.css", "pic.svg"):
            report = self.run_repo(extra={rel: "see http://10.1.2.3:8080/files/x"})
            self.assertFails(report, f"{PAGE}/{rel}", "a private network address", rel)

    def test_private_text_fails_in_a_binary_file(self):
        report = self.run_repo(extra={"doc.pdf": b"%PDF-1.4\xff\xfe /Author (C:\\Users\\someone)"})
        self.assertFails(report, f"{PAGE}/doc.pdf", "a user folder")

    def test_the_allow_list_turns_a_failure_into_a_look(self):
        html = page("<p>Routers often default to 192.168.0.1.</p>")
        self.assertFails(self.run_repo(html=html), f"{PAGE}/index.html", "192.168.0.1")
        report = self.run_repo(html=html, meta={**GOOD_META, "allow": ["192.168.0.1"]})
        self.assertClean(report)
        self.assertTrue(any("allows the text" in w and "192.168.0.1" in w for w in report.warnings))

    def test_the_allow_list_allows_only_what_it_names(self):
        html = page("<p>192.168.0.1 and 192.168.0.2</p>")
        report = self.run_repo(html=html, meta={**GOOD_META, "allow": ["192.168.0.1"]})
        self.assertFails(report, f"{PAGE}/index.html", "192.168.0.2")

    def test_allowing_the_start_of_a_path_does_not_allow_the_path(self):
        for text, starts in (
            (r"C:\work\client\notes.txt", ("C:\\", "C:", r"C:\work", "C:\\work\\client\\")),
            ("/c/work/project/notes.txt", ("/c/work/", "/c/work/project/")),
            ("/home/someone/x/y", ("/home/someone", "/home/")),
            (r"\\fileserver\share\x", (r"\\fileserver\share", "\\\\")),
            ("file:///C:/x.pdf", ("file:/", "file:///")),
            (r"%USERPROFILE%\notes\x", ("%USERPROFILE%",)),
        ):
            for start in starts:
                report = self.run_repo(html=page(f"<p>{text}</p>"),
                                       meta={**GOOD_META, "allow": [start]})
                self.assertFails(report, f"{PAGE}/index.html", "holds", (text, start))

    def test_allowing_an_address_does_not_allow_what_is_kept_at_it(self):
        for text, allowed in (
            ("http://192.168.0.1:8080/shows/book.pdf", ("192.168.0.1", "http://192.168.0.1")),
            ("http://localhost:3000/private/client/", ("localhost", "http://localhost:3000")),
            ("localhost:3000/private/client", ("localhost",)),
            ("http://fileserver/share/client/notes.docx", ("http://fileserver",)),
            (r"C:\Users\some one\Documents\client\notes.txt", (r"C:\Users\some",)),
            (r"C:\Program Files\Tool\tool.exe", (r"C:\Program",)),
        ):
            for entry in allowed:
                report = self.run_repo(html=page(f"<p>{text}</p>"),
                                       meta={**GOOD_META, "allow": [entry]})
                self.assertFails(report, f"{PAGE}/index.html", "holds", (text, entry))

    def test_allowing_the_whole_path_allows_it_in_page_json_too(self):
        path = r"C:\Windows\System32\drivers\etc\hosts"
        report = self.run_repo(html=page(f"<p>The file is {path}.</p>"),
                               meta={**GOOD_META, "allow": [path]})
        self.assertClean(report)
        self.assertTrue(any("allows the text" in w for w in report.warnings))

    def test_a_folder_git_would_leave_out_fails_inside_a_page(self):
        for rel in ("__pycache__/x.txt", ".cache/x.txt", "more/.git/config"):
            report = self.run_repo(extra={rel: "x"})
            self.assertFails(report, f"{PAGE}/{rel.rsplit('/', 1)[0]}", "not a kind of folder", rel)


class Contacts(Case):
    def test_contacts_are_looked_at_and_do_not_fail(self):
        report = self.run_repo(html=page("<p>Call (202) 555-0100 or write clerk@example.gov</p>"))
        self.assertClean(report)
        self.assertTrue(any('phone number "(202) 555-0100"' in w for w in report.warnings))
        self.assertTrue(any('email address "clerk@example.gov"' in w for w in report.warnings))

    def test_phones(self):
        for text in ("202-555-0100", "(202) 555-0100", "202.555.0100", "+1 202 555 0100",
                     "+12025550100", "+44 20 7946 0958"):
            self.assertTrue(cp.find_contacts(text), text)
        for text in ("2026-09-28", "1,234,567", "51.5007, -0.1246", "202-555-010",
                     "ISBN 978-3-16-148410-0", "2025550100", "a+12"):
            self.assertEqual(cp.find_contacts(text), [], text)

    def test_hidden_contacts(self):
        for text in ("jo&#64;example.com", "mailto:jo%40example.com", "jo [at] example [dot] com",
                     "jo(at)example(dot)co(dot)uk"):
            self.assertTrue(cp.find_contacts(text), text)

    def test_a_version_is_not_an_address(self):
        for text in ("chart.js@4.4.1", "d3@7", "lib@1.2.3-beta", "npm i pkg@latest"):
            self.assertEqual(cp.find_contacts(text), [], text)

    def test_an_email_address_is_found_whole(self):
        for text, whole in (
            ("write jo.bloggs+news@mail.example.co.uk today", "jo.bloggs+news@mail.example.co.uk"),
            ("<jo@example.com>", "jo@example.com"),
            ("to=jo@example.com&x=1", "jo@example.com"),
            ("jo@example.com.", "jo@example.com"),
            ("x" * 64 + "@example.com", "x" * 64 + "@example.com"),
        ):
            self.assertEqual([hit for _, hit in cp.find_contacts(text)], [whole], text)
        # a name longer than an address may carry is still found, by the end of it
        self.assertTrue(cp.find_contacts("x" * 80 + "@example.com"))
        # wrapped over a line, or indented
        for text in ("jo  [ at ]  example  [ dot ]  com", "jo\n    [at] example [dot] com",
                     "jo      [at]\n\t\texample\n        [dot]      com"):
            self.assertEqual(len(cp.find_contacts(text)), 1, text)


class Speed(Case):
    # Each text is the worst case for one pattern. A pattern that reads the text once for
    # every letter in it takes minutes at this size, and one that reads it once takes
    # well under a second, so the limit is loose enough for a slow machine.
    LIMIT = 20.0

    def test_a_long_text_is_read_once(self):
        import time
        size = 200_000
        texts = [unit * (size // len(unit)) for unit in (
            "10.1.2.", "a.b-", "a@b.", "jo [at] ", "x" * 50, "A" * 61 + "\n", "/a ",
            "C:\\x y\\", "a://b@", "'../", "ab: ", " a b c d\\", "jo [at] x [dot] ")]
        # one quote that is never closed, and one name with nothing but space after it
        texts += ["'" + "./" * (size // 2) + " ", "'" + "../" * (size // 3) + " ",
                  "jo" + " " * size, "jo [at]" + " " * size + "x",
                  "C:\\x" + " y" * (size // 2), "http://" + "a" * size + ","]
        for text in texts:
            unit = text[:12]
            start = time.perf_counter()
            cp.find_private(text)
            cp.find_contacts(text)
            cp.code_addresses(text)
            cp.code_paths(text)
            cp.css_addresses(text)
            self.assertLess(time.perf_counter() - start, self.LIMIT, unit)


class Noindex(Case):
    def test_accepted(self):
        for tag in (NOINDEX, '<META NAME="ROBOTS" CONTENT="NOINDEX">',
                    "<meta content='nofollow, noindex' name='robots'>",
                    '<meta name="robots" content="none"/>', '<meta name=" robots " content=" NoIndex ">'):
            html = f"<html><head>{tag}<title>t</title></head><body></body></html>"
            self.assertClean(self.run_repo(html=html), tag)

    def test_refused(self):
        for html in (
            "<html><head></head><body></body></html>",
            '<html><head><meta name="robots" content="index"></head></html>',
            '<html><head><meta name="googlebot" content="noindex"></head></html>',
            f"<html><head><!-- {NOINDEX} --></head></html>",
            '<html><head><meta name="robots" content="noindexing"></head></html>',
            f"<html><head></head><body><p>{NOINDEX.replace('<', '&lt;')}</p></body></html>",
            f"<html><head><title>{NOINDEX}</title></head></html>",
            f"<html><head><template>{NOINDEX}</template></head></html>",
            f"<html><head><noscript>{NOINDEX}</noscript></head></html>",
            f"<html><head><script>var s = '{NOINDEX}';</script></head></html>",
            f"<html><head></head><body><textarea>{NOINDEX}</textarea></body></html>",
            f"<html><head></head><body><svg>{NOINDEX}</svg></body></html>",
            f"<html><head></head><body><p>text</p>{NOINDEX}</body></html>",
            f"<html><body>{NOINDEX}</body></html>",
            f"{NOINDEX}<p>no head element at all</p>",
            f"<html><head></head>{NOINDEX}<p>after the head, and no body tag</p></html>",
        ):
            self.assertFails(self.run_repo(html=html), f"{PAGE}/index.html", "noindex", html)

    def test_a_second_robots_tag_that_allows_indexing_fails(self):
        html = f'<html><head>{NOINDEX}<meta name="robots" content="index, follow"></head></html>'
        self.assertFails(self.run_repo(html=html), f"{PAGE}/index.html", "does not say noindex")

    def test_every_html_file_needs_it_whatever_its_suffix(self):
        for rel in ("more/detail.html", "b.htm", "c.xhtml", "d.shtml", "E.HTML"):
            report = self.run_repo(extra={rel: "<html><head></head><body>x</body></html>"})
            self.assertFails(report, f"{PAGE}/{rel}", "noindex", rel)

    def test_a_self_closed_inert_element_does_not_hide_what_follows(self):
        html = f"<html><head><svg/><template/>{NOINDEX}</head></html>"
        self.assertClean(self.run_repo(html=html))


class Addresses(Case):
    def test_where_an_address_leads(self):
        cases = {
            cp.INSIDE: ("style.css", "./img/a.png", "img/../a.png", "#top", "?q=1", "more/",
                        f"https://drakontas.github.io/pages/{PAGE}/a.png",
                        f"/pages/{PAGE}/a.png"),
            cp.OUTSIDE: ("/style.css", "../shared/a.css", "img/../../a.png", "..", "./../a",
                         "..\\a.css", "%2e%2e/2026-08-other/", ".%2E/2026-08-other/",
                         ".&#10;./2026-08-other/", "https:../2026-08-other/a.png", "/pages/",
                         "https://drakontas.github.io/pages/2026-08-other/",
                         "//drakontas.github.io/pages/", "https://DRAKONTAS.github.io/",
                         f"/pages/{PAGE}/../2026-08-other/", f"/pages/{PAGE}/%2e%2e/x"),
            cp.EXTERNAL: ("https://example.org/a", "//cdn.example.org/a.js", "http://example.org/",
                          "https:/\\evil.example/x.js", "https:\\/evil.example/x.js",
                          "ht&#9;tps://evil.example/x.js", "https:&#10;//evil.example/x.js",
                          "\x01https://evil.example/x.js", " https://evil.example/x.js"),
            cp.INLINE: ("data:image/png;base64,AAAA", "mailto:x@example.org", "tel:+12025550100",
                        "blob:abc"),
            cp.FORBIDDEN: ("javascript:location='../x'", "JavaScript:alert(1)", "ftp://example.org/a",
                           "vbscript:x", "https://user:pw@example.org/", "https://cdn.example.org@evil.example/x.js"),
        }
        for want, urls in cases.items():
            for url in urls:
                self.assertEqual(cp.classify(url, PAGE)[0], want, repr(url))

    def test_a_folder_whose_name_begins_the_same_is_another_folder(self):
        self.assertEqual(cp.classify(f"/pages/{PAGE}-two/a.png", PAGE)[0], cp.OUTSIDE)

    def test_declared_addresses_match_on_host_and_whole_path_steps(self):
        declared = ["https://cdn.example.org/lib/"]
        for url in ("https://cdn.example.org/lib/a.js", "https://CDN.example.org/lib/x/y.css"):
            self.assertTrue(cp.is_declared(url, declared), url)
        for url in ("https://cdn.example.org.evil.example/lib/a.js", "https://cdn.example.org/library/a.js",
                    "https://cdn.example.org/", "http://cdn.example.org/lib/a.js",
                    "https://cdn.example.org:8443/lib/a.js", "https://evil.example/cdn.example.org/lib/"):
            self.assertFalse(cp.is_declared(url, declared), url)
        for url in ("https://cdn.example.org/lib/../evil.js", "https://cdn.example.org/lib/%2e%2e/evil.js",
                    "https://cdn.example.org/lib/x/..\\..\\..\\evil.js"):
            self.assertFalse(cp.is_declared(url, declared), url)
            self.assertFalse(cp.is_declared(cp.classify(url, PAGE)[1], declared), url)
        self.assertTrue(cp.is_declared("https://cdn.example.org/lib/a.js", ["https://cdn.example.org"]))
        self.assertTrue(cp.is_declared("https://cdn.example.org/lib/a.js", ["https://cdn.example.org/lib"]))
        self.assertFalse(cp.is_declared("https://cdn.example.org/lib2/a.js", ["https://cdn.example.org/lib"]))

    def test_what_may_be_declared(self):
        for entry, want in (("http://x.example.org/a.js", "must begin https://"),
                            ("https://", "full host"), ("https://cdn", "full host"),
                            ("//cdn.example.org/", "must begin https://"),
                            ("https://u:p@cdn.example.org/", "plain address"),
                            ("https://cdn.example.org/a?x=1", "plain address"),
                            ("https://cdn.example.org:port/", "cannot be read")):
            report = self.run_repo(meta={**GOOD_META, "external_resources": [entry]})
            self.assertFails(report, f"{PAGE}/page.json", want, entry)


class Loading(Case):
    OUTSIDE_SITE = (
        '<script src="https://cdn.example.org/x.js"></script>',
        '<script type="module">import * as d from "https://cdn.example.org/npm/d@7/+esm";</script>',
        "<script>fetch('https://api.example.org/data')</script>",
        '<script>const u = {"a":"https:\\/\\/api.example.org\\/x"};</script>',
        "<script>import('//cdn.example.org/a.js')</script>",
        '<link rel="stylesheet" href="//fonts.example.org/f.css">',
        '<link rel="STYLESHEET" href="https://fonts.example.org/f.css">',
        '<link rel="apple-touch-icon" href="https://x.example.org/i.png">',
        '<link rel="preconnect" href="https://x.example.org">',
        '<link href="https://x.example.org/no-rel.css">',
        '<link rel="canonical stylesheet" href="https://x.example.org/a.css">',
        '<img srcset="https://x.example.org/a.png 2x">',
        '<img srcset="a.png 1x, https://x.example.org/a.png 2x">',
        '<style>@import "https://x.example.org/a.css";</style>',
        '<style>@import"https://x.example.org/a.css";</style>',
        "<style>@import url('https://x.example.org/a.css');</style>",
        "<style>a{background:\\75rl(https://x.example.org/a.png)}</style>",
        "<style>a{background:url(ht\\74ps://x.example.org/a.png)}</style>",
        '<style>a{background:image-set("https://x.example.org/a.png" 1x)}</style>',
        '<div style="background:url(https://x.example.org/a.png)"></div>',
        '<iframe src="https://maps.example.org/embed"></iframe>',
        '<frame src="https://x.example.org/f.html">',
        '<svg><image href="https://x.example.org/a.png"/></svg>',
        '<svg><image xlink:href="https://x.example.org/a.png"/></svg>',
        '<svg><use href="https://x.example.org/s.svg#a"/></svg>',
        '<input type="image" src="https://x.example.org/a.png">',
        '<table background="https://x.example.org/a.png"></table>',
        '<a href="more.html" ping="https://track.example.org/p">x</a>',
        '<video src="https://x.example.org/v.mp4"></video>',
        '<video poster="https://x.example.org/p.png"></video>',
        '<audio src="https://x.example.org/a.mp3"></audio>',
        '<embed src="https://x.example.org/e.swf">',
        '<object data="https://x.example.org/o.pdf"></object>',
        '<track src="https://x.example.org/t.vtt">',
        '<source src="https://x.example.org/s.mp4">',
        '<script src="https:/\\evil.example/x.js"></script>',
        '<script src="ht&#9;tps://evil.example/x.js"></script>',
        '<div data-src="https://x.example.org/lazy.png"></div>',
        '<button onclick="location=\'https://x.example.org/\'">x</button>',
        '<meta property="og:image" content="https://x.example.org/a.png">',
    )

    def test_an_undeclared_outside_address_fails(self):
        for tag in self.OUTSIDE_SITE:
            self.assertFails(self.run_repo(html=page(tag)), f"{PAGE}/index.html", "on another site", tag)

    def test_declaring_it_passes_and_is_shown_to_the_owner(self):
        html = page('<script src="https://cdn.example.org/lib/a.js"></script>')
        meta = {**GOOD_META, "external_resources": ["https://cdn.example.org/lib/"]}
        report = self.run_repo(html=html, meta=meta)
        self.assertClean(report)
        self.assertTrue(any("may load from" in w and "cdn.example.org" in w for w in report.warnings))

    def test_a_loose_declaration_does_not_cover_a_look_alike_host(self):
        html = page('<script src="https://cdn.example.org.evil.example/x.js"></script>')
        meta = {**GOOD_META, "external_resources": ["https://cdn.example.org"]}
        self.assertFails(self.run_repo(html=html, meta=meta), f"{PAGE}/index.html", "on another site")

    def test_in_script_and_style_files(self):
        for rel, text in (("app.js", "import('https://cdn.example.org/a.js')"),
                          ("app.mjs", 'export * from "https://cdn.example.org/a.js"'),
                          ("style.css", '@import"https://x.example.org/a.css";'),
                          ("style.css", "a{background:url( 'https://x.example.org/a.png' )}"),
                          ("pic.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script href="https://x.example.org/a.js"/></svg>'),
                          ("pic.svg", '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://x.example.org/a.png"/></svg>')):
            report = self.run_repo(extra={rel: text})
            self.assertFails(report, f"{PAGE}/{rel}", "on another site", text)

    def test_leaving_the_folder_from_a_script_file(self):
        for rel, text in (("app.js", "fetch('../2026-08-other/data.json')"),
                          ("app.mjs", 'import {a} from "/pages/2026-08-other/a.js";')):
            report = self.run_repo(extra={rel: text})
            self.assertFails(report, f"{PAGE}/{rel}", "outside its own folder", text)

    def test_a_path_held_in_code_as_text_may_be_allowed_and_a_loaded_one_may_not(self):
        html = page("<script>const parts = ['/skins/content', '../'];</script>")
        self.assertFails(self.run_repo(html=html), f"{PAGE}/index.html", 'names "/skins/content"')
        meta = {**GOOD_META, "allow": ["/skins/content", "../"]}
        report = self.run_repo(html=html, meta=meta)
        self.assertClean(report)
        self.assertTrue(any("allows the text" in w and "/skins/content" in w for w in report.warnings))
        for tag in ('<img src="../x/a.png">', '<a href="../">up</a>',
                    "<style>a{background:url(../x/a.png)}</style>"):
            allowed = {**GOOD_META, "allow": ["../x/a.png", "../"]}
            self.assertFails(self.run_repo(html=page(tag), meta=allowed), f"{PAGE}/index.html",
                             "outside its own folder", tag)

    def test_what_a_page_may_name_freely(self):
        for tag in ('<a href="https://example.org/">cite</a>',
                    '<blockquote cite="https://example.org/source">q</blockquote>',
                    '<p>Read https://example.org/report for more.</p>',
                    '<img src="data:image/png;base64,AAAA">',
                    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"></svg>',
                    '<script>var ns = "http://www.w3.org/2000/svg";</script>',
                    '<script>if (location.protocol === "https:") { go(); }</script>',
                    '<a href="mailto:clerk@example.gov">write</a>',
                    '<a href="#top">top</a>', '<a href="more/detail.html">more</a>',
                    '<form action="https://example.org/search"></form>',
                    '<svg xmlns:dc="https://example.org/ns/dc"></svg>',
                    "<script>fetch('./data.json'); fetch('data/more.json')</script>",
                    f"<script>fetch('/pages/{PAGE}/data.json')</script>",
                    "<script>const per = '/month', cut = s.split('/'), c = '/* x */';</script>",
                    '<img srcset="img/a.png 1x, ./img/b.png 2x">'):
            self.assertClean(self.run_repo(html=page(tag)), tag)
        head = '<link rel="canonical" href="https://example.org/x"><link rel="stylesheet" href="style.css">'
        self.assertClean(self.run_repo(html=page(head=head)))

    def test_leaving_the_folder(self):
        for tag, want in (('<a href="../2026-08-other/">x</a>', "links to"),
                          ('<a href="/pages/">home</a>', "links to"),
                          ('<a href="https://drakontas.github.io/pages/2026-08-other/">x</a>', "links to"),
                          ('<a href="%2e%2e/2026-08-other/">x</a>', "links to"),
                          ('<area href="../x/">', "links to"),
                          ('<form action="../x/"></form>', "links to"),
                          ('<button formaction="../x/">b</button>', "links to"),
                          ('<img src="../shared/logo.png">', "loads"),
                          ('<link rel="stylesheet" href="/pages/site.css">', "loads"),
                          ('<svg><image xlink:href="../2026-08-other/a.png"/></svg>', "loads"),
                          ('<style>a{background:url(../x/a.png)}</style>', "loads"),
                          ('<style>@import "../x/a.css";</style>', "loads"),
                          ('<style>a{background:image-set("../x/a.png" 1x)}</style>', "loads"),
                          ('<img srcset="img/a.png 1x, ../x/a.png 2x">', "loads"),
                          ('<a href="more.html" ping="../x/p">x</a>', "loads"),
                          ("<script>fetch('../2026-08-other/data.json')</script>", "names"),
                          ("<script>fetch(`../2026-08-other/${name}.json`)</script>", "names"),
                          ("<script>fetch('/pages/2026-08-other/data.json')</script>", "names"),
                          ("<script>fetch('/data/all.json')</script>", "names"),
                          ('<script type="module">import {a} from "../2026-08-other/a.js";</script>', "names"),
                          ('<script>fetch("./../2026-08-other/data.json")</script>', "names"),
                          ('<button onclick="location=\'../2026-08-other/\'">x</button>', "names")):
            self.assertFails(self.run_repo(html=page(tag)), f"{PAGE}/index.html",
                             "outside its own folder", tag)
            self.assertFails(self.run_repo(html=page(tag)), f"{PAGE}/index.html", want, tag)

    def test_kinds_of_address_no_page_may_use(self):
        for tag in ('<a href="javascript:location=\'../x\'">x</a>', '<iframe src="javascript:x"></iframe>',
                    '<a href="https://user:pw@example.org/">x</a>', '<img src="ftp://example.org/a.png">'):
            self.assertFails(self.run_repo(html=page(tag)), f"{PAGE}/index.html", "not a kind of address", tag)

    def test_elements_no_page_may_hold(self):
        for tag, want in (('<base href="https://evil.example/">', "<base>"),
                          ('<base target="_blank">', "<base>"),
                          ('<meta http-equiv="refresh" content="0;url=https://evil.example/">', "refresh"),
                          ('<meta http-equiv="Refresh" content="5">', "refresh"),
                          ('<iframe srcdoc="<img src=https://x.example.org/a.png>"></iframe>', "srcdoc")):
            self.assertFails(self.run_repo(html=page(head=tag)), f"{PAGE}/index.html", want, tag)


class Files(Case):
    def test_a_good_page_passes_clean(self):
        report = self.run_repo(
            html=page('<img src="img/a.png"><a href="https://example.org/source">source</a>',
                      head='<link rel="stylesheet" href="style.css">'),
            extra={"style.css": "body{background:url(img/bg.png)}", "img/a.png": b"\x89PNG\r\n\x1a\n\x00"})
        self.assertClean(report)
        self.assertEqual(report.warnings, [])

    def test_missing_index_and_metadata(self):
        repo = Repo(meta="absent")
        self.addCleanup(repo.close)
        (repo.folder / "index.html").unlink()
        report = repo.check()
        self.assertFails(report, PAGE, "has no index.html")
        self.assertFails(report, f"{PAGE}/page.json", "missing")

    def test_index_html_is_matched_in_lower_case(self):
        repo = Repo()
        self.addCleanup(repo.close)
        (repo.folder / "index.html").rename(repo.folder / "INDEX.tmp")
        (repo.folder / "INDEX.tmp").rename(repo.folder / "Index.html")
        self.assertFails(repo.check(), PAGE, "has no index.html")

    def test_kinds_of_file_a_page_may_not_hold(self):
        for rel in ("app.js.map", ".env", ".hidden.txt", "notes", "run.sh", "data.yaml", "a.webmanifest",
                    "page.php", "more/.htaccess"):
            self.assertFails(self.run_repo(extra={rel: "x"}), f"{PAGE}/{rel}", "not a kind of file", rel)

    def test_a_file_over_the_limit_fails(self):
        repo = Repo(extra={"big.png": b"x"})
        self.addCleanup(repo.close)
        with open(repo.folder / "big.png", "wb") as handle:
            handle.truncate(cp.MAX_FILE_BYTES + 1)
        self.assertFails(repo.check(), f"{PAGE}/big.png", "The limit is 25 MB")
        with open(repo.folder / "big.png", "wb") as handle:
            handle.truncate(cp.MAX_FILE_BYTES)
        self.assertClean(repo.check())

    def test_text_that_is_not_utf8_fails(self):
        for rel in ("index.html", "app.js", "style.css", "pic.svg", "data.json"):
            report = self.run_repo(extra={rel: b"\xff\xfe<html>\x00"})
            self.assertFails(report, f"{PAGE}/{rel}", "cannot be read as UTF-8", rel)

    def test_a_byte_order_mark_is_accepted(self):
        bom = b"\xef\xbb\xbf"
        report = self.run_repo(html=None, meta=None,
                               extra={"page.json": bom + json.dumps(GOOD_META).encode(),
                                      "index.html": bom + page().encode()})
        self.assertClean(report)

    def test_a_link_in_a_page_folder_fails(self):
        repo = Repo(root={"elsewhere/secret.txt": "x"})
        self.addCleanup(repo.close)
        try:
            os.symlink(repo.root / "elsewhere", repo.folder / "linked", target_is_directory=True)
            os.symlink(repo.root / "elsewhere" / "secret.txt", repo.folder / "linked.txt")
        except (OSError, NotImplementedError):
            self.skipTest("this machine does not let the test make a link")
        report = repo.check([PAGE])
        self.assertFails(report, f"{PAGE}/linked", "is a link")
        self.assertFails(report, f"{PAGE}/linked.txt", "is a link")


class Metadata(Case):
    def test_edges(self):
        cases = (
            ("cannot be read as JSON", "{title:"),
            ("cannot be read as JSON", ""),
            ("must be a JSON object", "[]"),
            ('"session" is required', json.dumps({**GOOD_META, "session": "  "})),
            ('"title" is required', json.dumps({k: v for k, v in GOOD_META.items() if k != "title"})),
            ('"summary" is required', json.dumps({**GOOD_META, "summary": 3})),
            ('"created" must be', json.dumps({**GOOD_META, "created": "2026-9-28"})),
            ('"created" must be', json.dumps({**GOOD_META, "created": "2026-09-32"})),
            ('"created" must be', json.dumps({**GOOD_META, "created": "2026-09-00"})),
            ("but the folder is dated", json.dumps({**GOOD_META, "created": "2026-10-01"})),
            ('"external_resources" must be a list', json.dumps({**GOOD_META, "external_resources": "https://x.org/"})),
            ('"external_resources" must be a list', json.dumps({**GOOD_META, "external_resources": [3]})),
            ('"allow" must be a list', json.dumps({**GOOD_META, "allow": "localhost"})),
            ('"allow" must be a list', json.dumps({**GOOD_META, "allow": [""]})),
            ('"project" is not a field', json.dumps({**GOOD_META, "project": "anything"})),
            ('"author" is not a field', json.dumps({**GOOD_META, "author": "anyone"})),
        )
        for want, body in cases:
            self.assertFails(self.run_repo(meta=body), f"{PAGE}/page.json", want, body)

    def test_page_json_is_read_for_private_text_too(self):
        report = self.run_repo(meta={**GOOD_META, "summary": r"Made from C:\work\client\notes"})
        self.assertFails(report, f"{PAGE}/page.json", "a drive path")


class RepoFiles(Case):
    ROOT_PAGE = f"<html><head>{NOINDEX}</head><body>Nothing is listed.</body></html>"

    def test_the_repo_s_own_files_pass(self):
        path = r"C:\work\x"
        report = self.run_repo(root={
            "README.md": "# pages", "index.html": self.ROOT_PAGE, "404.html": self.ROOT_PAGE,
            ".nojekyll": "", ".gitignore": "__pycache__/", "tools/check_pages.py": "# 10.1.2.3",
            "tests/test_check_pages.py": f"# localhost, {path}, clerk@example.gov",
            "tests/made_up.json": json.dumps(["10.1.2.3", "localhost", path, "clerk@example.gov"]),
            "decisions/ADR-0001-published-pages.md": "# ADR",
            ".github/workflows/check.yml": "name: check", "tools/__pycache__/x.pyc": b"\x00"})
        self.assertClean(report)
        # nothing but the list, which has no main here to be compared with
        self.assertEqual([w for w in report.warnings if not w.startswith("tests/made_up.json")], [])
        self.assertEqual(len(report.warnings), 4)

    def test_contact_details_in_the_repo_s_own_files_fail(self):
        listed = json.dumps(["clerk@example.gov"])
        for rel, body, want in (
            ("README.md", "write to someone@example.com", "email address"),
            ("decisions/ADR-0002-next.md", "call 202-555-0100", "phone number"),
            (".github/workflows/check.yml", "# jo [at] example [dot] com", "email address"),
            ("index.html", self.ROOT_PAGE.replace("Nothing", "someone@example.com, nothing"),
             "email address"),
        ):
            report = self.run_repo(root={"tests/made_up.json": listed, rel: body})
            self.assertFails(report, rel, want, body)
            self.assertFails(report, rel, "does not list", body)
        report = self.run_repo(root={"tests/made_up.json": listed,
                                     "README.md": "an example: clerk@example.gov"})
        self.assertClean(report)
        self.assertEqual([w for w in report.warnings if not w.startswith("tests/made_up.json")], [])

    def test_a_root_page_s_code_names_no_path(self):
        body = f"<html><head>{NOINDEX}<script>fetch('./{PAGE}/data.json')</script></head></html>"
        self.assertFails(self.run_repo(root={"index.html": body}), "index.html", "name no page")

    def test_the_check_and_its_tests_hold_listed_values_only(self):
        listed = json.dumps(["10.1.2.3"])
        for rel, body, want in (
            ("tests/test_more.py", "# 10.9.8.7", '"10.9.8.7"'),
            ("tests/test_more.py", r"# C:\work\real\notes.txt", "a drive path"),
            ("tests/test_more.py", "# someone@example.com", "email address"),
            ("tests/test_more.py", "# call 202-555-0100", "phone number"),
            ("tools/check_pages.py", "# http://fileserver:5000/x", "a host name"),
            ("tests/made_up.json", json.dumps(["10.1.2.3", "10.9.8.7"]), None),
        ):
            report = self.run_repo(root={"tests/made_up.json": listed, rel: body})
            if want is None:
                self.assertClean(report, "the list may name a value no test holds")
            else:
                self.assertFails(report, rel, want, body)
                self.assertFails(report, rel, "does not list", body)
        self.assertFails(self.run_repo(root={"tests/test_more.py": "# 10.1.2.3"}),
                         "tests/test_more.py", "does not list", "no list at all")

    def test_a_list_of_made_up_values_that_cannot_be_read_fails(self):
        for body, want in (("{", "cannot be read as JSON"), ('{"a": 1}', "must be a list"),
                           ('["10.1.2.3", 4]', "must be a list")):
            self.assertFails(self.run_repo(root={"tests/made_up.json": body}), "tests/made_up.json", want)

    def test_a_file_named_like_a_page_folder_fails(self):
        report = self.run_repo(root={"2026-09-loose": "a file, not a folder"})
        self.assertFails(report, "2026-09-loose", "is not one of the repo's own files")

    def test_a_link_at_the_root_fails(self):
        repo = Repo(root={"tools/check_pages.py": "# nothing"})
        self.addCleanup(repo.close)
        try:
            os.symlink(repo.root / "tools", repo.root / "2026-09-linked", target_is_directory=True)
            os.symlink(repo.root / "tools" / "check_pages.py", repo.root / "LICENSE")
        except (OSError, NotImplementedError):
            self.skipTest("this machine does not let the test make a link")
        report = repo.check()
        self.assertFails(report, "2026-09-linked", "is a link")
        self.assertFails(report, "LICENSE", "is a link")

    def test_one_of_the_repo_s_own_files_over_the_limit_fails(self):
        report = self.run_repo(root={"README.md": "x" * (cp.MAX_REPO_FILE_BYTES + 1)})
        self.assertFails(report, "README.md", "The limit for one of the repo's own files")

    def test_anything_else_outside_a_page_folder_fails(self):
        for rel in ("secret.pdf", "notes.txt", "x.xhtml", "CNAME", "screenshot.png", "robots.txt",
                    "tools/leak.html", "tools/notes.txt", "decisions/draft-page.html",
                    "decisions/notes.md", ".github/x.txt", ".github/workflows/deploy.sh",
                    "tests/data/x.json"):
            report = self.run_repo(root={rel: "x"})
            self.assertFails(report, rel, "is not one of the repo's own files", rel)

    def test_a_stray_folder_fails(self):
        for rel in (".playwright-mcp/page.yml", "node_modules/x/index.js", "Drafts/x.html"):
            report = self.run_repo(root={rel: "x"})
            self.assertFails(report, rel.split("/")[0], "not one of the repo's own folders", rel)

    def test_private_text_in_the_repo_s_own_files_fails(self):
        for rel in ("README.md", "index.html", "decisions/ADR-0002-next.md", ".github/workflows/check.yml"):
            body = self.ROOT_PAGE.replace("Nothing", "10.1.2.3 nothing") if rel.endswith(".html") \
                else "see 10.1.2.3"
            self.assertFails(self.run_repo(root={rel: body}), rel, "a private network address", rel)

    def test_root_pages_need_noindex_and_name_no_page(self):
        for body, want in (("<html><body>Nothing is listed.</body></html>", "noindex"),
                           (f'<html><head>{NOINDEX}</head><body><a href="{PAGE}/">x</a></body></html>',
                            "name no page"),
                           (f'<html><head>{NOINDEX}</head><body><a href="https://example.org/">x</a></body></html>',
                            "name no page"),
                           (f'<html><head>{NOINDEX}<script src="https://x.example.org/a.js"></script></head></html>',
                            "on another site")):
            self.assertFails(self.run_repo(root={"index.html": body}), "index.html", want, body)

    def test_a_root_page_that_is_not_text_is_reported_and_does_not_crash(self):
        report = self.run_repo(root={"index.html": b"\xff\xfe\x00<"})
        self.assertFails(report, "index.html", "cannot be read as UTF-8")

    def test_naming_one_folder_checks_only_that_folder(self):
        report = self.run_repo(root={"drafts/x.txt": "x"}, only=[PAGE])
        self.assertClean(report)


class Branches(Case):
    """What a branch changes, compared with main."""

    GOOD = "bot@users.noreply.github.com"

    def repo(self, email: str = GOOD) -> Repo:
        repo = Repo(root={"README.md": "# pages"})
        self.addCleanup(repo.close)
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "config", "user.name", "bot")
        self.git(repo, "config", "user.email", self.GOOD)
        self.git(repo, "config", "commit.gpgsign", "false")
        self.git(repo, "add", "README.md")
        self.git(repo, "commit", "-q", "-m", "start")
        self.git(repo, "checkout", "-q", "-b", f"page/{PAGE}")
        self.git(repo, "config", "user.email", email)
        return repo

    def git(self, repo: Repo, *args: str) -> None:
        subprocess.run(["git", "-C", str(repo.root), *args], check=True, capture_output=True)

    def commit(self, repo: Repo, *paths: str, message: str = "page", force: bool = False) -> None:
        self.git(repo, "add", *(["-f"] if force else []), "--", *paths)
        self.git(repo, "commit", "-q", "-m", message)

    def test_a_branch_that_adds_one_page_passes(self):
        repo = self.repo()
        self.commit(repo, PAGE)
        self.assertClean(repo.check([PAGE], "main"))

    def test_a_page_not_yet_committed_is_seen_too(self):
        repo = self.repo()
        self.assertClean(repo.check([PAGE], "main"))

    def test_anything_beside_the_page_fails_committed_or_not(self):
        for rel, committed in (("notes.txt", True), ("notes.txt", False), ("tools/check_pages.py", True),
                               (".playwright-mcp/page.yml", False), ("README.md", True)):
            repo = self.repo()
            repo.write(rel, "changed")
            self.commit(repo, PAGE, *([rel] if committed else []))
            self.assertFails(repo.check([PAGE], "main"), "branch", f'touches "{rel}"', (rel, committed))

    def test_two_pages_on_one_branch_fail(self):
        repo = self.repo()
        repo.write("2026-09-second/index.html", page())
        repo.write("2026-09-second/page.json", json.dumps(GOOD_META))
        self.commit(repo, PAGE, "2026-09-second")
        self.assertFails(repo.check([PAGE], "main"), "branch", "touches 2 page folders")

    def test_the_page_asked_about_must_be_the_page_changed(self):
        repo = self.repo()
        repo.write("2026-09-second/index.html", page())
        repo.write("2026-09-second/page.json", json.dumps(GOOD_META))
        self.commit(repo, "2026-09-second")
        self.git(repo, "checkout", "-q", "main")
        self.git(repo, "merge", "-q", f"page/{PAGE}")
        self.git(repo, "checkout", "-q", "-b", "page/another")
        self.commit(repo, PAGE)
        self.assertFails(repo.check(["2026-09-second"], "main"), "branch", "the page asked about")

    def test_a_change_to_the_repo_s_own_files_alone_passes(self):
        repo = self.repo()
        self.commit(repo, PAGE)
        self.git(repo, "checkout", "-q", "main")
        self.git(repo, "merge", "-q", f"page/{PAGE}")
        self.git(repo, "checkout", "-q", "-b", "tooling")
        repo.write("README.md", "# pages, revised")
        self.commit(repo, "README.md")
        self.assertClean(repo.check(None, "main"))

    def test_a_commit_under_a_personal_address_fails(self):
        for email in ("someone@example.com", "bot@users.noreply.github.com.example.org", "t@t"):
            repo = self.repo(email)
            self.commit(repo, PAGE)
            report = repo.check([PAGE], "main")
            self.assertFails(report, "branch", "not a GitHub no-reply address", email)
            self.assertFalse(any(email in f for f in report.failures), "the address is not repeated")

    def test_the_committer_s_address_is_read_as_well_as_the_author_s(self):
        repo = self.repo()
        self.git(repo, "add", "--", PAGE)
        subprocess.run(["git", "-C", str(repo.root), "commit", "-q", "-m", "page"], check=True,
                       capture_output=True,
                       env={**os.environ, "GIT_COMMITTER_EMAIL": "someone@example.com"})
        self.assertFails(repo.check([PAGE], "main"), "branch", "not a GitHub no-reply address")

    def test_a_commit_message_is_read(self):
        for message, want in (("page, made at http://10.1.2.3:8080/x", "a private network address"),
                              ("page\n\nFrom C:\\work\\client\\notes.txt", "a drive path"),
                              ("page\n\nReviewed-by: Someone <someone@example.com>", "email address")):
            repo = self.repo()
            self.commit(repo, PAGE, message=message)
            report = repo.check([PAGE], "main")
            self.assertFails(report, "branch", "has a commit message", message)
            self.assertFails(report, "branch", want, message)

    def test_a_phone_number_in_a_commit_message_is_looked_at(self):
        repo = self.repo()
        self.commit(repo, PAGE, message="page\n\nThe box office is on 202-555-0100")
        report = repo.check([PAGE], "main")
        self.assertClean(report)
        self.assertTrue(any("commit message" in w and "202-555-0100" in w for w in report.warnings))

    def test_a_commit_message_may_name_a_no_reply_address(self):
        repo = self.repo()
        self.commit(repo, PAGE, message="page\n\nCo-Authored-By: A tool <noreply@anthropic.com>\n"
                                        "Co-Authored-By: bot <1+bot@users.noreply.github.com>")
        report = repo.check([PAGE], "main")
        self.assertClean(report)
        self.assertEqual(report.warnings, [])

    def no_page(self, repo: Repo) -> None:
        """Take the sample page away, so that a branch is about the repo's own files alone."""
        (repo.folder / "index.html").unlink()
        (repo.folder / "page.json").unlink()
        repo.folder.rmdir()

    def test_a_file_forced_past_gitignore_fails(self):
        repo = self.repo()
        self.no_page(repo)
        self.git(repo, "checkout", "-q", "-b", "tooling", "main")
        repo.write(".gitignore", "__pycache__/\n")
        self.commit(repo, ".gitignore")
        self.assertClean(repo.check(None, "main"))
        repo.write("tools/__pycache__/x.pyc", b"\x00")
        self.assertClean(repo.check(None, "main"), "left out by git, so never served")
        self.commit(repo, "tools/__pycache__/x.pyc", force=True)
        report = repo.check(None, "main")
        self.assertFails(report, "branch", 'touches "tools/__pycache__/x.pyc"')
        self.assertFails(report, "branch", "Git leaves such a file out")
        self.assertEqual(len(report.failures), 1, report.failures)

    def test_a_new_made_up_value_is_shown(self):
        repo = self.repo()
        self.git(repo, "checkout", "-q", "main")
        repo.write("tests/made_up.json", json.dumps(["10.1.2.3"]))
        self.git(repo, "add", "--", "tests/made_up.json")
        self.git(repo, "commit", "-q", "-m", "list")
        self.git(repo, "checkout", "-q", "-b", "tooling")
        self.no_page(repo)
        repo.write("tests/made_up.json", json.dumps(["10.1.2.3", "10.9.8.7"]))
        repo.write("tests/test_more.py", "# 10.9.8.7")
        # before anything is committed, with a ref named and with none
        for ref in ("main", None):
            report = repo.check(None, ref)
            self.assertClean(report, ref)
            shown = [w for w in report.warnings if w.startswith("tests/made_up.json")]
            self.assertEqual(len(shown), 1, (ref, report.warnings))
            self.assertIn('"10.9.8.7"', shown[0])
            self.assertIn("before the branch is pushed", shown[0])
        # and after
        self.commit(repo, "tests/made_up.json", "tests/test_more.py")
        for ref in ("main", None):
            shown = [w for w in repo.check(None, ref).warnings if w.startswith("tests/made_up.json")]
            self.assertEqual(len(shown), 1, (ref, shown))
        # once it is on main, it is no longer new
        self.git(repo, "checkout", "-q", "main")
        self.git(repo, "merge", "-q", "tooling")
        self.assertEqual(repo.check(None, None).warnings, [])

    def test_a_list_with_no_repo_around_it_is_read_without_one(self):
        report = self.run_repo(root={"tests/made_up.json": json.dumps(["10.1.2.3"]),
                                     "tests/test_more.py": "# 10.1.2.3"})
        self.assertClean(report)
        # with nothing to compare the list with, every value on it is new
        shown = [w for w in report.warnings if w.startswith("tests/made_up.json")]
        self.assertEqual(len(shown), 1, report.warnings)
        self.assertIn('"10.1.2.3"', shown[0])

    def test_a_branch_is_never_compared_with_itself(self):
        repo = self.repo()
        self.no_page(repo)
        repo.write("tests/made_up.json", json.dumps(["10.9.8.7"]))
        repo.write("tests/test_more.py", "# 10.9.8.7")
        self.commit(repo, "tests/made_up.json", "tests/test_more.py")
        self.git(repo, "branch", "-q", "-D", "main")
        shown = [w for w in repo.check(None, None).warnings if w.startswith("tests/made_up.json")]
        self.assertEqual(len(shown), 1, shown)
        self.assertIn('"10.9.8.7"', shown[0])

    def test_no_way_to_compare_is_a_failure_not_a_pass(self):
        repo = self.repo()
        self.assertFails(repo.check([PAGE], "no-such-ref"), "git", "cannot compare")
        bare = Repo()
        self.addCleanup(bare.close)
        self.assertFails(bare.check([PAGE], "main"), "git", "cannot compare")


class CommandLine(Case):
    def test_verdicts_and_exit_codes(self):
        tool = str(Path(cp.__file__))
        for html, code, verdict in ((page(), 0, "RESULT: OK"),
                                    (page("<p>(202) 555-0100</p>"), 0, "RESULT: NEEDS A LOOK"),
                                    ("<html></html>", 1, "RESULT: FAILED")):
            repo = Repo(html=html)
            self.addCleanup(repo.close)
            done = subprocess.run([sys.executable, tool, "--root", str(repo.root), PAGE],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, code, done.stdout)
            self.assertIn(verdict, done.stdout.splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
