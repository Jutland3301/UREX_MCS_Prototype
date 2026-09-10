# Bitbucket workflow for v0.3-alpha

Do not commit the alpha directly to `main`. Keep the current `main` commit as
v0.1 and publish the alpha on its own branch.

## 1. Preserve the current main commit

Run these commands inside the existing Bitbucket checkout before copying the
alpha files into it:

```bash
git switch main
git pull --ff-only origin main
git status
git tag --list v0.1
git tag -a v0.1 -m "UREX MCS simulator v0.1"  # only if the tag is absent
git push origin v0.1                           # only after creating it
```

Stop if `git status` shows changes that should not be included or if the tag
already points somewhere unexpected.

## 2. Create the alpha branch

```bash
git switch -c simulator-v0.3-alpha
```

Copy the extracted v0.3-alpha files into the checkout only after switching to
this branch. Then review and publish them:

```bash
git status
git diff --stat
python -m unittest discover -v
git add .
git commit -m "Add operator-controlled simulator experiments"
git push -u origin simulator-v0.3-alpha
```

The Bitbucket `main` branch remains on v0.1. Open a pull request later only
after the GUI test and team review. A branch changes files in the working
directory, but it does not overwrite the history or files stored on `main`.
