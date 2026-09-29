# ADR-0001 — A public home for small, finished pages

- **Status:** Accepted
- **Date:** 2026-09-28
- **Decided by:** owner rulings, 2026-09-28 (two tap menus, then written)

## Context

Work done with Claude sometimes ends in a web page: a piece of research, a comparison, a
briefing for one event. Such a page is limited in scope. It does not need a repo of its own,
and the project it came from is often private or is the wrong home for it.

The owner asked for a place where a page like that can be reached publicly, and where several
unrelated tasks can each land a page without getting in each other's way.

## Decision

1. **One public repo, served by GitHub Pages from the root of `main`.** Everything in it is
   public by definition, so no setting can expose more than was meant. The address is
   `https://drakontas.github.io/pages/`.
2. **One folder per task, named `<YYYY-MM>-<slug>`.** The slug is lower-case words joined by
   single hyphens. The folder holds `index.html`, every file the page uses, and `page.json`.
   The page's address is the folder's name.
3. **A page holds its own files.** It loads and links nothing from another folder or from the
   root. Two tasks therefore never write the same file, and no change to one page can break
   another.
4. **Nothing is shared and edited by hand.** There is no common stylesheet and no index file
   that every task must add a line to.
5. **The repo is a closed world.** Every file is one of the repo's own, which the check
   names, or sits in a page folder. Anything else fails.
6. **The site has no listing** (owner). The landing page names no page. Every HTML file asks
   search engines not to index it, with `<meta name="robots" content="noindex">`.
7. **The owner approves each page before it is pushed** (owner). A pushed branch in a public
   repo is already public, so the approval comes before the push, not before the merge.
   The same holds for a branch that adds a value to `tests/made_up.json`: the owner reads
   each new value before that branch is pushed.
8. **A page stays until the owner asks for it to be removed** (owner). Nothing expires.
9. **Every page arrives on its own branch, `page/<folder>`, through a pull request that
   touches that folder and nothing else.** Nothing is committed on `main` directly.
10. **What a page depends on is declared.** Every outside address in its code, its styles or
    a loading attribute is listed in `page.json`, and the owner sees the list when approving.
    A link a reader follows by choice needs no declaration.
11. **`page.json` holds a fixed set of fields.** The file is public. It names the session
    that made the page, as an opaque id, and never the project.
12. **A pull request is judged by the check as it stands on `main`.** A branch's own copy of
    the check is not the one that judges it. The one exception is the branch that first
    brings the check in, which holds no page. The limits of this are under "What the rules
    do not give".
13. **No build step.** Files are served as they are written (`.nojekyll`).

## What the rules do not give

- **No listing is not privacy.** The site lists nothing, but this repo's file list names
  every page, and its source can be read and searched on GitHub by anyone. Nothing that
  needs protecting goes here.
- **`noindex` is a request, and it covers HTML only.** A crawler may ignore it. A PDF, an
  image or a data file in a page's folder cannot carry the tag at all, and GitHub Pages
  gives no way to send the same request as a header.
- **A `robots.txt` would do nothing.** Crawlers read it only at the root of a host, which for
  this site is `drakontas.github.io/`, a different repo.
- **Removal is not recall.** Removing a page takes it off the site. The repo's history keeps
  it, and anyone may have copied it while it was up.
- **The check cannot read names.** It catches machine paths and private addresses, and
  flags email addresses and phone numbers for a person to look at. Whether a name belongs
  to a private person is a question only a reader can answer, and it is asked before every
  approval.
- **The check reads what is written, not what runs.** An address that code assembles from
  pieces is invisible to it. A declared outside script can also change after the owner
  approved the page. A page that must not change keeps its scripts in its own folder.
- **The check does not read inside a PDF or an image.** It finds a machine path or a private
  address only where the file holds it as plain text. Author names and similar details in a
  file's properties are for the person reading the page to look at.
- **A path with a space in it may be found only in part.** The check follows a path
  through a folder's name of up to five words. It stops at a longer name, at two spaces
  together, at an apostrophe or a quote in a name, and at a space in the last name of the
  path, because nothing tells any of these from the end of the path.
  What the check prints, and what `allow` must match, is the path as far as it was
  followed. A person who allows a path reads the rest of the line it stands on.
- **A private host name is found only in an address.** `http://` and the name of a machine
  is found. The name alone, as in "copy it to" and a name, is not, because code is full of
  words that look the same.
- **A path that code holds in quotes is judged by its look.** The check cannot tell a path
  the code loads from one it holds as text. It takes a path that climbs out of the folder,
  and one from the root of the site that has a second step or a file's ending. A single
  word after a slash is left alone.
- **The check is required only where a rule on `main` requires it.** The rule is the
  owner's to set: a pull request for every change, the `check` job passing, and no direct
  push. Without the rule, a failing check does not stop a merge.
- **The workflow that runs on a pull request is the branch's own.** A branch that changes
  `.github/` changes what runs, and may run no check at all. The check on `main` refuses
  such a change on a page's branch only while the branch's workflow still runs it. A person
  reads every change under `.github/` before it is merged.
- **The check reads a branch's commits, and not those already on `main`.** A commit made on
  github.com carries the address the account is set to show. The first commit here does.

## Alternatives rejected

- **Pages on the private project repo.** A personal account's Pages site is public even when
  its repo is private, so the privacy is only apparent. Pages publishes a whole branch or
  folder, so a wrong source setting would expose project files. The page would also sit in a
  repo it does not belong to.
- **The account's root site** (`drakontas.github.io`). Shorter addresses, but it spends the
  account's one root site on short-lived work.
- **A generated listing page.** Easier to find things, but it advertises every page to
  anyone who finds one.
- **Expiry dates with a scheduled removal.** Offered with a 90-day default. The owner chose
  to keep pages until asked, so that a link that was handed out keeps working.
- **Sessions publishing on their own after the check passes.** Faster, but a missed name is
  public before anyone has looked, and cannot be recalled.
- **Serving from `/docs`.** It would keep the repo's own files off the site, but it makes
  every address longer, and the repo is public in any case.
- **A `project` field in `page.json`.** It would say where a page came from, but the file is
  served with the page, and the project is often private.

## Consequences

- A session in any project can publish a page by following `README.md`. It needs no knowledge
  of any other page.
- The repo's own files (`README.md`, `tools/`, `tests/`, `decisions/`) are served along with
  the pages. They are public already. The check and its tests hold private-looking values
  on purpose, and every one is named in `tests/made_up.json`; a value that is not named
  there fails. The list says a value is made up. It cannot prove it, so the check shows
  each new entry, and the owner reads it before the branch is pushed. The repo's other
  files hold no contact details beyond those on the list.
- A page that names an outside address in its code must declare it, even where the address
  is only data. That is friction, accepted so that the list the owner sees is complete.
- Adding a new kind of repo file takes two pull requests: one that teaches the check the
  name, and one that adds the file.
- The repo grows without limit. Pages are small; if size ever matters, removal is by request.
