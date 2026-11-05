# ryukoku-writing

A Claude Code plugin for Ryukoku University students who write reports and graduation theses in Japanese or English. You ask the research question, build the argument and write the text. The AI in this plugin asks questions, searches for and verifies sources, proposes notation/format unification, and raises review questions. 日本語: [README.md](README.md)

> **This is not an official Ryukoku University tool.** The university's name is used only to describe who the plugin is for and which rules it follows (Ryukoku University, "Guidelines for students on the use of generative AI", 2025-11-14). No logo or emblem is used. The reading of the guideline is the plugin author's interpretation, not the university's official view. **The instructions of your university, faculty and instructor always take precedence**, in particular course-level instructions (guideline III-3: the syllabus or what is said in class). The guideline is revised over time (IV): check for updates with `python3 tools/rk/rk.py guideline-check`, and keep the plugin updated. Students of other universities should replace the rules with their own (`.ryukoku/config.yml` and the skills).

## Install

```
/plugin marketplace add imkoga002/student-plugins
/plugin install ryukoku-writing@student-plugins
```

From a terminal, the Claude Code CLI can also install it in one line (`--marketplace` adds the marketplace first if it has not been added yet; this form was checked against `claude plugin install --help` during development, so check your version's help):

```
claude plugin install ryukoku-writing --marketplace imkoga002/student-plugins
```

Requirements: Claude Code, bash (macOS, Linux, Git Bash on Windows), Python 3 (standard library only). Optional: pandoc (Word, LaTeX, PDF export), LuaLaTeX with TeX Live's collection-langjapanese (Japanese PDF), mermaid-cli `mmdc` (diagram images), Git and GitHub.

## How it works

- **The AI never writes your manuscript (`manuscript/`).** The hooks block every tool, Bash and PowerShell included; a change that slips through is detected as "changed while an AI tool was running" and the checks fail until you decide. The AI also never writes your questions (`research/questions.md`) or your thinking log (`thinking/`).
- **Only an allow-list runs without asking.** Of the AI's shell commands, only (a) the plugin's own tools (`tools/rk/rk.py`, `./rk`, ... and only while their content matches the shipped files) and (b) a fixed set of read-only commands (`ls`, `cat`, `grep`, `git status`, `git log`, ...) run without a prompt. Anything else, and anything that cannot be analysed completely, asks you first and names the command (with stronger wording when it may run a file the AI wrote). Read it and allow only if needed.
- **Even notation fixes are proposals.** Only full/half-width forms of letters, digits, kana and a few marks (％ （） ： ； ！ ？), the punctuation system (、/， and 。/．), spaces next to Japanese text, heading numbers (computed by the tool from level and order; the AI cannot choose them), diagram settings and the form of a citation of the same work can be proposed; you look at each diff and decide. A proposal that changes any other character (a word, digit, decimal point, sign, mark or citation page) cannot be made: the tool reduces both sides with the allowed transforms only and compares them character by character (when the proposal is made and again when it is applied).
- **Human decisions exist only as signatures made with your passphrase:** VERIFIED (you read the source), proposal decisions, style-rule approvals, resolved comments, section sign-offs, the pre-submission check, the daily AI-use summary. Neither the passphrase nor a private key is stored; the key is derived when you sign and discarded afterwards. `./rk check` and GitHub CI verify the signatures.
- **Research leaves a record.** The search tools run only for a question id you wrote in `research/questions.md` and log every search (database, query, date, hit count, question, purpose). The AI reports candidates to read, not conclusions.

Why: guideline III-4 strongly warns against presenting AI-made work, even in part, as your own. The plugin makes it hard for AI changes to reach your submission unnoticed, and hard for the AI to pose as your confirmation.

## First steps (one terminal session)

1. In Claude Code: `/plugin marketplace add …` and `/plugin install …` (above)
2. Open Claude Code in your thesis folder and run `/ryukoku-writing:start` (or say "start my thesis project"); answer the language questions and the AI initialises the folder
3. Open your own terminal in that folder and run **`./rk setup`** once (Windows cmd: `rk setup`; PowerShell: `.\rk.cmd setup`, since the default execution policy may refuse `.\rk.ps1`. **Setup and the notebook have not been tried on Windows yet**): passphrase, course AI policy, training opt-out check, Git (if Git has no name or e-mail yet, it asks; they need not be real); you sign once
4. **Reopen Claude Code in that folder** (otherwise parts of the recording and detection do not apply)
5. Write your text
6. Ask the AI for review, research and notation fixes; it leaves question comments, search records and candidates, and proposal files
7. To decide, ask the AI to "open the evidence notebook" (it starts the page and gives you `http://127.0.0.1:…/`). Show each item, check the diff or source data, choose, then enter your passphrase **once**: each chosen item is signed with the hash of its content. There is no accept-all button

Seven steps, one terminal session (step 3; checked on Linux; the AI starts the page). Later decisions are made on the page (the terminal commands such as `./rk apply` remain available). If part of a batch cannot be signed (e.g. two proposals that change the same line), you get a result per item (signed / not signed, with the reason) and the signed items leave the list.

## About the passphrase

- At least 10 characters, and either 3-4 unrelated words or 16+ characters (repeated characters, digits only or a common word are refused). The public key is in the project, so a short passphrase can be brute-forced offline. **Never type it into the chat, to the AI or into e-mail**; only into your terminal or the local evidence-notebook page.
- **Before typing it, check the "running code" location and version** shown in the terminal and next to the page's passphrase box. The human commands and the page check, before asking, that they run from the plugin location Claude Code recorded (the SessionStart hook records it) and that their files match the shipped MANIFEST; otherwise they stop without asking. This is a check made by the plugin's code while it runs: a program running with your permissions can rewrite both where `./rk` goes and the checking code itself (see "Does not guarantee"). The prompt before anything outside the allow-list runs, and the detection of rewrites of the launcher target and its record, make that less likely and visible.
- **If someone (or the chat) may know it**: register a new one with `./rk setup`. The new key is endorsed with the current passphrase, then the old key is revoked, and the revocation (signed with the old key) names the new key as its successor. An endorsement by a revoked key is invalid whatever its time, except for that successor, so a key added with the leaked passphrase is not trusted, while your new key stays trusted in CI. Signatures made before the revocation stay valid.
- **If you forgot it**: register a new one with `./rk setup`. The new key becomes this computer's trust root and the root change is recorded in `.ryukoku/root-changes.jsonl`; commit it on main and push from your own terminal (pre-push asks for `yes`). CI prints the root change and the new fingerprint first. **This relies on your advisor checking that fingerprint with you in person.**
- A message of the form "my passphrase is …", or a short one-line message that is your registered passphrase (also typed in full-width characters), is stopped before it is sent. Other forms, such as the passphrase inside a longer sentence, may not be caught.
- On another computer run `./rk trust` and compare the fingerprints with the one you noted.
- Show the fingerprint (16 characters such as `8C77-CA09-…`) to your advisor at the first meeting. GitHub CI checks that main's history has a single root commit, takes the signers of the first `signers.json` in that history as its trust root and prints their fingerprint on the **first line** ("[trust root]"). **The advisor's procedure**: compare that first line of the PR's CI output with the noted fingerprint; if it differs, do not accept the PR and ask the student; if a "root changed" line appears, check the new fingerprint with the student in person. The same check works with HANDOFF.md for folder hand-overs.

## Commands

Human-only, in your own terminal (each ends with one passphrase entry): `./rk setup`, `./rk notebook`, `./rk apply`, `./rk verify`, `./rk style`, `./rk resolve`, `./rk changes`, `./rk disclose`, `./rk signoff`, `./rk optout`, `./rk trust`, `./rk import-docx`, `./rk update-tools`.

If you change the checking tools or CI files yourself (`tools/`, `.github/`, `.githooks/`, `./rk`), read the diff and confirm it with `./rk sign guarded tools --decision confirmed` (in a PR: `guarded pr`); `./rk check` fails until then.

Anyone (the AI too): `./rk check` (same as CI; `--submit` before submission), `./rk facts` (facts for the AI-use disclosure; you write the statement), `python3 tools/rk/rk.py search …` (logged automatically), `python3 tools/rk/rk.py refcheck check` (identifier resolution and metadata matching), `python3 tools/rk/rk.py export docx` (also LaTeX, PDF), `python3 tools/rk/rk.py bundle` (HANDOFF.md for an advisor without Git).

The skills are written in Japanese; when `feedback_lang: en` is set, they answer in English. Standing principles: [CONSTITUTION.md](CONSTITUTION.md) (Japanese, with an English digest).

## Settings

- `.ryukoku/config.yml` (the hooks act only where this file exists): manuscript language and feedback language (separate), course, AI policy from the syllabus (`ai_policy: allowed | limited | prohibited | unknown`). **limited / prohibited change what the tools do** (ask / block). No course setting allows the AI to write your text, questions, claims or conclusions.
- Plugin options (`/plugin`): `feedback_lang` (default for new projects), `crossref_mailto` (optional, empty by default, never embedded), `cinii_appid` (secret; never shown or logged).

## What this plugin guarantees, and what it does not

**Guarantees (blocked, or detected and kept, while the hooks run)**
- AI tool calls that write the manuscript, your questions and thinking log, the records of human decisions, the checking tools, Claude Code's settings, `~/.ryukoku-writing`, Git/Python configuration (`.git/`, a file named `.git`, `~/.gitconfig`, site-packages, sitecustomize, ...), shell startup files, directories on PATH, autostart entries, `.vscode` or `.envrc` are blocked by the hooks, for every tool; a write whose content looks like Git/Python configuration asks wherever it is placed.
- Of the AI's shell commands, anything outside the allow-list (the plugin's own tools and a fixed set of read-only commands) asks you first.
- A change that happens while an AI tool runs is detected as a change during an AI tool call, written to the AI-use log kept in Git (each line carries the hash of the previous one) and to a second note on this computer, and `./rk check` and CI fail until you decide and sign.
- A human state counts only with an Ed25519 signature by a trusted signer's passphrase. GitHub CI checks that main has a single root commit and trusts only the signers of the first `signers.json` in that history (and recorded root changes) and keys endorsed from them; a revoked key's endorsement counts only for the successor it signed. A PR that changes `tools/`, `.github/` and the like does not pass without your signed confirmation.
- A proposal cannot change any character except by the allowed transforms (full/half width of letters, digits, kana and a few marks, the punctuation system, spaces next to Japanese, heading numbers computed by the tool, diagram settings, the form of a citation of the same work); it cannot add a citation or a page (tests test_proposals.AllowList, test_round4.HeadingNumbers).

**Does not guarantee**
- That you read before you sign. A signature is your statement that you checked.
- Anything you allow at a prompt. Allowed code or commands can do anything you can (copy the plugin and redirect `./rk`, fake the passphrase page, rebuild the detection records and notes, switch the hooks off). The location and MANIFEST check, change detection and the second note leave traces, but cannot stop it. Read the code when you are asked.
- Circumvention through combinations of allow-listed commands. The allow-listed `git` (read-only) runs without a prompt only when the repository used is this project's own `.git`; a sibling repo or a code-executing config such as `core.fsmonitor` asks. `export` copies only the allowed keys from the project's pandoc defaults (filters, templates, Lua readers/writers named as `from`/`to`, alternate pdf-engines are refused), and runs pandoc, LaTeX and mmdc in a temporary folder outside the project, so configuration placed in the project is not read. Even so, configuration the AI placed, or the student placed, might make an allow-listed command run another program (there may be gaps).
- Detection of ghostwriting or question-delegation requests (the context injected before sending) is vocabulary-based and misses many rephrasings (about half of the verifier's new phrasings). The last safeguard is structural: the AI cannot write the manuscript or the questions.
- Comments created on the evidence-notebook page have no identity check (student only, unsigned); an advisor's comments enter only through the signed terminal import `./rk import-docx`.
- Anything while the hooks are off: with `disableAllHooks: true` in `.claude/settings*.json`, or with the plugin disabled or removed, nothing is blocked, recorded or detected. `./rk check`, `./rk setup` and CI report the disabling settings as errors and SessionStart mentions them; a removal leaves no setting, so `./rk check` only shows the date of the last Claude Code start the hooks recorded. `claude plugin` / `claude config` operations from the AI's shell are blocked by the hooks.
- GitHub CI: whether a `pull_request` workflow runs the definition as changed in the PR was not confirmed (**unverified**; the independent verification pointed out that GitHub generally runs the PR's definition). So when a PR changes `.github/`, do not trust that PR's CI result; read the diff. Branch protection on private repositories needs GitHub Pro or above (GitHub Docs, About protected branches, https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
- Detection of a process detached from a tool call that writes later (such changes look like your own edits); as a backstop, the section sign-off always shows the diff since your last signature.
- The quality of the AI's replies.
- Behaviour on Windows and macOS, which was not tested on real machines (see SELF-ASSESSMENT.md).

## Privacy

Hooks and checks make no network requests; only the searches, verification and guideline check you allow do. Prompt text is never logged (only categories). Search candidates are kept outside Git (`.ryukoku/cache/`) and those older than 24 hours are deleted at the next search, SessionStart or `./rk check` (J-STAGE terms art. 3(5)); they stay while the computer is not used.

## License

MIT ([LICENSE](LICENSE)).
