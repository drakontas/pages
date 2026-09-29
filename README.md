# pages

A public home for small, finished web pages: a piece of research, a comparison, a briefing
for one event. Each page is limited in scope and does not need a repo of its own.

Served at `https://drakontas.github.io/pages/`. The rules and the reasons for them are in
[`decisions/ADR-0001-published-pages.md`](decisions/ADR-0001-published-pages.md).

**Everything here is public, and what is pushed cannot be recalled.** That covers the pages,
every other file in a page's folder, this repo's history, and the text of every commit and
pull request. The site has no list of its pages, but this repo's file list is one, and
anyone can read it.

## What never goes in a page

- A private person's name, phone number, email address, home address or schedule.
- Text or images under someone else's copyright or licence.
- Anything from a private project that the project's own rules keep private, its name included.
- A path on the machine the page was made on, or an address on a private network.

## Layout

```
index.html, 404.html      the landing page and the not-found page; they name no page
<YYYY-MM>-<slug>/         one folder per task: this is a page
    index.html
    page.json
    ...                   every other file the page uses
tools/check_pages.py      the check
tests/                    the check's own tests
tests/made_up.json        every private-looking value the check and its tests may hold
decisions/                why the repo is the way it is
```

Nothing else may sit outside a page folder. The check fails any other file or folder.

A page's address is its folder's name:
`https://drakontas.github.io/pages/2026-09-example/`.

## page.json

```json
{
  "title": "What the page is called",
  "created": "2026-09-28",
  "session": "the id of the Claude session that made it",
  "summary": "One sentence on what the page is for."
}
```

`created` falls in the month the folder is named for. The file is public. It holds these
four fields and, where needed, the two below. Any other field fails the check.

| Optional field | What it is for |
|---|---|
| `external_resources` | A list of `https://` addresses the page may name in its code or load from. An address covers everything beneath it. |
| `allow` | A list of exact pieces of text the check would refuse, such as a router's default address in a page about home networks. |

An `allow` entry is the whole of what the check found, as the check prints it between
quotes. The start of a path allows nothing, as far as the check can follow the path. It
cannot follow one through a space in its last name, an apostrophe or a quote, two spaces
together, or a folder's name of more than five words, so read the rest of the line before
allowing a path. Both lists are
shown to the owner when the page is put up for approval.

## What the check looks at

| Rule | Why |
|---|---|
| Every HTML file has `<meta name="robots" content="noindex">` inside `<head>` | It is the only way to ask a search engine to leave a page out |
| A page loads and links nothing in another folder of this site, from its markup, its styles or a path in quotes in its code | No change to one page can break another |
| Every outside address in code, styles or a loading attribute is listed in `external_resources` | The owner sees what the page depends on, and what a reader's browser will contact |
| A link a reader follows by choice, `<a href>`, may lead anywhere outside this site | Citing a source is the point of most pages |
| No `<base>`, no refresh, no `srcdoc`, no `javascript:` address | Each one moves or hides where the page leads |
| No machine path, private network address or private host name, in any file or in a file written into another as base64 | It means nothing to a reader and says something about where the page was made |
| Only the kinds of file a page needs; no hidden files or folders, no links | Anything in the folder is served |
| A branch touches one page folder and nothing else | What goes public is exactly what was approved |
| A branch's commits are made under a GitHub no-reply address, and their messages hold no private text and no other email address | Commit details are public |
| Every private-looking value in `tools/` and `tests/` is named in `tests/made_up.json`, and so is every email address and phone number in the repo's other files | A value cannot arrive in the repo's own files without a `LOOK` line, which the owner reads before the branch is pushed |

Email addresses and phone numbers in a page are reported as `LOOK` and do not fail. A public
office's number is a fair thing to publish; only a person can tell whose it is.

**The check cannot read names, and it cannot see an address that code builds from pieces.**
It is a net under the approval, and does not replace it.

The check reads a branch's commits and not the ones already on `main`. A commit the owner
makes on github.com carries the address the owner's account is set to show.

## Publishing a page

1. **Work in your own checkout.** Use a fresh clone or `git worktree add`, never a checkout
   another session is using. Cut the branch `page/<folder>` from `origin/main`. Set the
   commit identity to a GitHub no-reply address.
2. **Build the page in its folder.** Put nothing anywhere else in the repo. Write each
   cited source into the page as an `<a href>` link. A list of source addresses held in a
   script as data is the first thing a research page fails on: there, every address must
   be declared. A script can read the address from the link.
3. **Run the check** and fix what fails:

   ```
   python tools/check_pages.py <folder> --changed-against origin/main
   ```

4. **Read the page and `page.json` for personal details.** The check cannot do this part.
5. **Ask the owner, and wait for a yes.** Nothing is pushed or committed to a shared place
   before it. A pushed branch is already public, and this site cannot preview a branch.
   Show the page privately: as a file on the owner's own network, or as a private Artifact.
   In a tap menu, give the owner:
   - the page's title and its summary from `page.json`;
   - every `LOOK` line from the check, as printed;
   - the `external_resources` and `allow` lists, if the page has them;
   - what you found in step 4, or that you found nothing.
6. **On a yes:** add the page folder alone (`git add <folder>`), commit, run step 3 once
   more, push the branch, open a pull request, wait for the check to pass, and merge. Then
   hand over the page's address.

A change to the page after the owner's yes needs a new yes.

Commit messages and pull requests are public too. Keep private project names, issue numbers
and people out of them.

## Changing or removing a page

A change follows the same six steps on a new branch. A removal is a pull request that
deletes the folder. It takes the page off the site. The history keeps it, and anyone may
have copied the page while it was up.

## Changing the check

A pull request that changes `tools/`, `tests/` or `.github/` touches no page folder. It is
judged by the check as it stands on `main`, so a branch cannot loosen the rule it is held to.

A test that needs a new private-looking value adds it to `tests/made_up.json` on the same
branch. Use a value that belongs to no one: an address from a range kept for examples, a
name such as `someone`. Never copy onto the list a value the check found in a file. If
the value is real, take it out of the file.

**Before a branch that changes `tests/made_up.json` is pushed**, run
`python tools/check_pages.py --changed-against origin/main`, show the owner every `LOOK`
line for `tests/made_up.json` in a tap menu, and wait for a yes. The check prints those
lines before anything is committed. A pushed branch is already public.

The workflow that runs on a pull request is the branch's own copy, so a change under
`.github/` is read by a person before it is merged. The check is a required one only once
the owner has set a rule on `main` that requires it.
