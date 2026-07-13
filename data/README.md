## Assignment Data Directory

This directory holds your **local assignment files**. Student submissions, answer keys, and grade templates live here so they stay:

- **Local** to your machine
- **Private** to your course
- **Untracked** by git (only this `README.md` is committed)

For each assignment, create a folder that matches your workflow profile name (for example `a1`, `a2`, `midterm`).

### Quick setup

```bash
# Option A: Let gradeline import from your Downloads folder (recommended)
./gradeline import --profile a2

# Option B: Organize files manually
mkdir -p data/a2/submissions
# Then move/copy your files into place:
# - Brightspace "Download All" folder  → data/a2/submissions/
# - Solutions PDF                     → data/a2/solutions.pdf
# - Brightspace grade CSV template    → data/a2/grades.csv
```

After this, run:

```bash
./gradeline quickstart --profile a2
```

`quickstart` will auto-detect everything under `data/a2/`, show you a confirmation table, and write a reusable profile for future runs.

### Expected structure

```text
data/
├── a2/                        ← one folder per assignment (matches your profile name)
│   ├── submissions/           ← unzipped Brightspace "Download All" folder
│   │   ├── 123 - Jane Doe/    ← student folders (Brightspace names them like this)
│   │   │   └── submission.pdf
│   │   ├── 456 - John Smith/
│   │   │   └── submission.pdf
│   │   └── ...
│   ├── solutions.pdf          ← the answer key / solutions PDF
│   └── grades.csv             ← Brightspace grade export template for this assignment
├── a3/
│   └── ...
```

You can choose any profile name (for example `a1`, `assignment2`, `midterm`), as long as you stay consistent between:

- the profile you pass to `./gradeline` (for example `--profile a2`)
- the subdirectory you create under `data/` (for example `data/a2/`)

### Where to get these files from Brightspace

| File / folder      | Where to download in Brightspace                          |
|--------------------|-----------------------------------------------------------|
| `submissions/`     | **Assignments** → select assignment → **Download All**    |
| `solutions.pdf`    | Your own answer key PDF (wherever you store it locally)  |
| `grades.csv`       | **Grades** → **Export** → select the assignment column   |

`grades.csv` should be the same template you use to upload grades back into Brightspace. The grader will write a `brightspace_grades_import.csv` based on this template.

### What happens next

Once `data/{profile}/` is populated, you can:

```bash
# One-shot import + quickstart flow
./gradeline import --profile a2
./gradeline quickstart --profile a2

# Or from the interactive menu:
./gradeline
```

From there, `quickstart` will:

- infer paths from `data/{profile}/`, prior runs, and recent Downloads
- validate that submissions, solutions, and the grade template exist
- write a profile under `.manual_runs/profiles/{profile}.toml`
- run grading and launch the review web app (unless you use `--no-run`)

