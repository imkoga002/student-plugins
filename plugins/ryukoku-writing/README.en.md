# ryukoku-writing

A Claude Code plugin for Ryukoku University students who write reports and graduation theses in Japanese or English. One idea is at its core: **the claims are yours, the writing goes fast with the AI, verification is rigorous, the record is honest.** Because the AI checks your claims and theories hard, you can put your own theory or niche observation into words without worrying that a weak point will slip through. 日本語: [README.md](README.md)

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

- **The claims are yours.** Tell the AI your fragments, hunches and niche observations; it asks questions and organises them into claim cards (`claims/C001.md`). A card keeps your own words verbatim, apart from the AI's paraphrase, and every warrant or objection the AI adds is marked `[ai_suggested]`. Only you confirm "this is my claim", with a button on the evidence notebook (or `./rk confirm`). The AI does not invent your research question or claims and present them as yours (it does help you think about how to frame a question).
- **Rigorous verification.** The AI checks claim cards and manuscript paragraphs for logic (Toulmin elements, the four kinds of leap, fallacies, causal-inference errors), support (citations, their ledger state, whether a saved excerpt really supports the claim), counter-evidence (searched and logged), novelty (positioned against the recorded searches, never asserted) and **whether AI-written text swapped your claim for another**. Results go to `review/verification/` with severity (fatal / major / minor), evidence and suggested revisions. Without an excerpt the support is "unchecked"; without a search, "not searched".
- **Fast writing, when the course allows it.** The course AI policy (`ai_policy` in `.ryukoku/config.yml`) decides what the AI may do with the manuscript:

  | ai_policy | AI writes to the manuscript |
  |---|---|
  | `allowed` | yes; each paragraph's provenance is recorded automatically |
  | `limited` | asks before every write (check what the syllabus allows) |
  | `unknown` (default) | asks before every write (check the syllabus) |
  | `prohibited` | no; no claim cards or notation proposals either. Research, verification (without rewritten text) and format checks remain |

  Its only material is what you confirmed: claim cards, argument maps, ledger sources and saved data. Claims, figures or sources that are not in the material are not added to the text; they are listed outside it as "additional suggestions".
- **An honest record.** When the AI writes or revises the manuscript, the hooks record which paragraph of which section in `.ryukoku/provenance.jsonl` (append-only; each line carries the hash of the previous one). It is a record, not an alarm: `./rk facts` turns it into disclosure facts (share of AI-written paragraphs, breakdown per section, purposes). Your own edits are estimated from the differences between AI tool calls, and the record says they are estimates. Right after a write, a mechanical check runs (ledger state of the citations, uncited assertions, figures without a source, candidates that differ from the claim card) and the AI shows you the result.
- **Fabrication is blocked by structure.** No bibliographic data, statistics or pages from memory. Sources are checked by identifier (DOI → Crossref / DataCite, NCID → CiNii Books, CRID → CiNii Research, NDL ID → NDL Search); a citation that is not in the ledger or is below IDENTITY_CONFIRMED fails `./rk check` at the submission stage (a warning while drafting). Figures in the manuscript are checked for a citation or a data reference.
- **Only two passphrase signatures.** VERIFIED (you read the original) and the final pre-submission confirmation (the content and the AI-use disclosure are correct). Every other decision (confirming a claim card, accepting a proposal, resolving a comment, approving a style rule, confirming you read a section, ...) is one button or one key, recorded with the hash of what you decided on.
- **Research leaves a record.** The search tools run only for a question id you wrote in `research/questions.md` and log every search (database, query, date, hit count, question, purpose), counter-evidence searches (`--purpose counter`) included.
- **Only an allow-list runs without asking.** Of the AI's shell commands, only (a) the plugin's own tools (while their content matches the shipped files) and (b) a fixed set of read-only commands run without a prompt. Anything else, and anything that cannot be analysed completely, asks you first and names the command.

Guideline III-4 warns against presenting AI-made work as your own. This plugin records what the AI wrote so that you can disclose it, and helps with the writing only when the course allows it. Follow the course's instructions and ask your instructor how to disclose. This is the plugin author's reading, not the university's official view.

## First steps (one terminal session)

1. In Claude Code: `/plugin marketplace add …` and `/plugin install …` (above)
2. Open Claude Code in your thesis folder and run `/ryukoku-writing:start` (or say "start my thesis project"); answer the language questions and the AI initialises the folder
3. Open your own terminal in that folder and run **`./rk setup`** once (Windows cmd: `rk setup`; PowerShell: `.\rk.cmd setup`, since the default execution policy may refuse `.\rk.ps1`. **Setup and the notebook have not been tried on Windows yet**): the course AI policy with a one-line source (e.g. the syllabus section), the training opt-out check, the passphrase (now, or at your first VERIFIED), Git (if Git has no name or e-mail yet, it asks; they need not be real)
4. **Reopen Claude Code in that folder** (otherwise parts of the recording and detection do not apply)
5. Tell the AI your idea. Once it has made a claim card, ask it to "open the evidence notebook" (it starts the page and gives you `http://127.0.0.1:…/`), check the card on the "Claim cards" tab and press "Record" if it is your claim
6. If the course allows it, ask the AI to draft or revise a section. It writes from confirmed cards, ledger sources and saved data only, and shows you the provenance and the mechanical check. You may of course write yourself
7. Ask for a verification ("verify this section against my claim cards") and fix fatal and major findings first. After reading an original, choose VERIFIED on the "Sources & claims" tab and sign with your passphrase
8. Before submission, on the "Before submission" tab (or `./rk signoff`), read the provenance and the disclosure statement, go through the checklist and sign the final confirmation with your passphrase

## About the passphrase

- It is needed only for VERIFIED and the final pre-submission confirmation. If you skipped it in `./rk setup`, `./rk verify` or `./rk signoff` registers it the first time.
- At least 10 characters, and either 3-4 unrelated words or 16+ characters (repeated characters, digits only or a common word are refused). The public key is in the project, so a short passphrase can be brute-forced offline. **Never type it into the chat, to the AI or into e-mail**; only into your terminal or the local evidence-notebook page.
- **Before typing it, check the "running code" location and version** shown in the terminal and next to the page's passphrase box. The human commands and the page check, before asking, that they run from the plugin location Claude Code recorded (the SessionStart hook records it) and that their files match the shipped MANIFEST; otherwise they stop without asking. This is a check made by the plugin's code while it runs: a program running with your permissions can rewrite both where `./rk` goes and the checking code itself (see "Does not guarantee").
- **If someone (or the chat) may know it**: register a new one with `./rk setup`. The new key is endorsed with the current passphrase, then the old key is revoked, and the revocation (signed with the old key) names the new key as its successor. An endorsement by a revoked key is invalid whatever its time, except for that successor. Signatures made before the revocation stay valid.
- **If you forgot it**: register a new one with `./rk setup`. The new key becomes this computer's trust root and the root change is recorded in `.ryukoku/root-changes.jsonl`; commit it on main and push from your own terminal (pre-push asks for `yes`). CI prints the root change and the new fingerprint first. **This relies on your advisor checking that fingerprint with you in person.**
- A message of the form "my passphrase is …", or a short one-line message that is your registered passphrase (also typed in full-width characters), is stopped before it is sent. Other forms may not be caught.
- On another computer run `./rk trust` and compare the fingerprints with the one you noted.
- Show the fingerprint (16 characters such as `8C77-CA09-…`) to your advisor. GitHub CI checks that main's history has a single root commit, takes the signers of the first `signers.json` in that history as its trust root and prints their fingerprint on the **first line** ("[trust root]"). **The advisor's procedure**: compare that first line of the PR's CI output with the noted fingerprint; if it differs, do not accept the PR and ask the student; if a "root changed" line appears, check the new fingerprint with the student in person. The same check works with HANDOFF.md for folder hand-overs.

## Commands

Human-only, in your own terminal: `./rk setup`, `./rk notebook`, `./rk confirm` (claim cards; a key press), `./rk verify` (VERIFIED is a passphrase signature), `./rk signoff` (the final confirmation, signed), `./rk apply`, `./rk style`, `./rk resolve`, `./rk changes`, `./rk disclose`, `./rk optout`, `./rk trust`, `./rk import-docx`, `./rk update-tools`.

Anyone (the AI too): `./rk check` (same as CI; `--submit` before submission), `./rk facts` (facts for the AI-use disclosure, with the provenance), `python3 tools/rk/rk.py claims new|list|lint`, `python3 tools/rk/rk.py provenance materials|show`, `python3 tools/rk/rk.py verification scaffold|lint`, `python3 tools/rk/rk.py search …` (logged automatically), `python3 tools/rk/rk.py refcheck check`, `python3 tools/rk/rk.py export docx` (also LaTeX, PDF), `python3 tools/rk/rk.py bundle` (HANDOFF.md for an advisor without Git).

The skills are written in Japanese; when `feedback_lang: en` is set, they answer in English. Standing principles: [CONSTITUTION.md](CONSTITUTION.md) (Japanese, with an English digest).

Notation and format may be fixed directly by the AI when the course allows it (provenance records the purpose "format"). If you want to see each hunk, use proposal files (format-proposals): they can change only full/half-width forms of letters, digits, kana and a few marks, the punctuation system, spaces next to Japanese, heading numbers, diagram settings and the form of a citation of the same work; a proposal that changes any other character cannot be made (checked when made and again when applied).

## Settings

- `.ryukoku/config.yml` (the hooks act only where this file exists): manuscript language and feedback language (separate), course, AI policy from the syllabus (`ai_policy`) with its source (`ai_policy_source`), allowed uses in a limited course (`ai_allowed_uses`: research, verify, format, review, language, ideas, draft). No setting lets the AI invent your questions or claims and present them as yours.
- Plugin options (`/plugin`): `feedback_lang` (default for new projects), `crossref_mailto` (optional, empty by default, never embedded), `cinii_appid` (secret; never shown or logged).

## What this plugin guarantees, and what it does not

**Guarantees (blocked, or recorded and detected, while the hooks run)**
- With `prohibited`, the hooks block AI writes to the manuscript (Write, Edit); with `limited` and `unknown` they ask first. A shell write (Bash, PowerShell) to the manuscript that the hooks can recognise is blocked under every policy, so that provenance is exact; a detour they cannot recognise (variable concatenation and the like) is not stopped beforehand and is recorded as below.
- A manuscript change made while an AI tool runs (a shell detour included) is recorded as provenance. AI-written paragraphs left in a course recorded as `prohibited` are a warning in `./rk check` and an error at the PR and submission stages.
- AI tool calls that write your questions and thinking log, the human records, the provenance log, the checking tools, Claude Code's settings, `~/.ryukoku-writing`, Git/Python configuration, shell startup files, directories on PATH, autostart entries, `.vscode` or `.envrc` are blocked, for every tool; a change that slips through is detected, written to the AI-use log and a second note on this computer, and `./rk check` and CI fail until you decide.
- Of the AI's shell commands, anything outside the allow-list asks you first.
- VERIFIED and the final confirmation count only with an Ed25519 signature by a trusted signer's passphrase; an unsigned record claiming VERIFIED is an error. GitHub CI trusts only the signers of the first `signers.json` in main's history (and recorded root changes) and keys endorsed from them.
- A light confirmation (a claim card and the like) that appears during an AI tool call is a detection. The decision records, the provenance log and the AI-use log are append-only, and CI requires them to extend the base branch's versions.
- A proposal file cannot change any character except by the allowed transforms; it cannot add a citation or a page (tests test_proposals.AllowList, test_round4.HeadingNumbers).

**Does not guarantee**
- That you read before you confirm or sign.
- **Attribution of your edits is an estimate.** A manuscript change outside an AI tool call is recorded as yours, including one made later by a detached process or by another program running with your permissions.
- **Light confirmations are not protected by cryptography.** They rest on the hooks, the in-call detection and the append-only checks. Code you allowed to run could write such a record outside an AI tool call, and it could not be told apart. Only the two decisions whose forgery would let unchecked material count as checked are signatures.
- The mechanical checks (swap candidates, uncited assertions, figures without a source) are word-list candidates, not verdicts; rephrased strengthening or widening is missed. The word lists are the author's choice and have not been evaluated on real manuscripts. The final judgement is the verification (claim-verifier) and yours.
- Anything you allow at a prompt. Allowed code can do anything you can (copy the plugin and redirect `./rk`, fake the passphrase page, rebuild records and notes, switch the hooks off). Traces remain, but it cannot be stopped.
- Circumvention through combinations of allow-listed commands, or through configuration the AI or you placed (there may be gaps).
- Detection of writing or question-delegation requests (the context injected before sending) is vocabulary-based and misses many rephrasings. The safeguards are structural: the policy gate on manuscript writes, provenance, and the questions closed to the AI.
- Anything while the hooks are off (`disableAllHooks: true`, or the plugin disabled or removed). `./rk check`, `./rk setup` and CI report the disabling settings; a removal leaves no setting.
- Comments created on the evidence-notebook page have no identity check (student only); an advisor's comments enter only through `./rk import-docx`.
- GitHub CI: whether a `pull_request` workflow runs the definition as changed in the PR was not confirmed (**unverified**; v1's independent verification pointed out that GitHub generally runs the PR's definition). When a PR changes `.github/`, do not trust that PR's CI result; read the diff. Branch protection on private repositories needs GitHub Pro or above (GitHub Docs, About protected branches, https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
- The quality of the AI's drafting and verification.
- Behaviour on Windows and macOS, which was not tested on real machines (see SELF-ASSESSMENT.md).

## Privacy

Hooks and checks make no network requests; only the searches, verification and guideline check you allow do. Prompt text is never logged (only categories); the provenance log holds paragraph hashes and line ranges, not the text. Search candidates are kept outside Git (`.ryukoku/cache/`) and those older than 24 hours are deleted at the next search, SessionStart or `./rk check` (J-STAGE terms art. 3(5)); they stay while the computer is not used.

## License

MIT ([LICENSE](LICENSE)).
