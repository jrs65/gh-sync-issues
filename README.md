# Synchronise Github Issues

This extension to [gh](https://github.com/cli/cli) is designed to synchronise issues
to/from a Github repository for a local YAML file for faster editing.

I have been using this for bulk creation and reorganisation of issues for project
management purposes which I can do much more efficiently in a local file. That means
that presently only a limited set of Github's issue functionality is exposed, in
particular only the following fields are supported:

- `title`: the main issue title
- `body`: that is the first text box
- `assignees`: a list of Github usernames
- `labels`: a list of string labels (these are created if they don't exist)

Not yet supported:

- `milestones`
- `comments`
- `projects`

## Getting Started

This is an installable Python package, however to be discoverable by `gh` it must be
installed by `gh` directly using:
```bash
$ gh extension install jrs65/gh-sync-issues
```
The first time the command is run it will construct a virtual environment and install
its dependencies into it (primarily `ruamel.yaml` and `pygithub`).

The first time you run you'll probably want to pull down any existing issues. That can be done by running
```bash
$ gh sync-issues pull issuesfile.yaml
```
which will try to identify the current repo and pull any existing issues into the
`issuefile.yaml` file. To specify a different source repository, use the `--repo`
option.

After making changes to the file you'll likely want to push the changes back up. This can be done using
```bash
$ gh sync-issues push issuesfile.yaml
```
This will summarise any changes and push them up. To see what would be done without
making changes you can use the `-n` option to do a dry-run.


## Example File

```yaml
- title: A new issue
  body: |-
    This issue will be added.
    When pushed, a number field will be added to this entry.
  assignees: [jrs65]

- number: 8
  title: An issue to update
  body: |-
    Any changed info here will be synced to issue 8 in the repo.
  assignees: []
  labels: [label]
```