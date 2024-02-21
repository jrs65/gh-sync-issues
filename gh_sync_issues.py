import dataclasses
import json
from pathlib import Path
import subprocess

import click
import github
import github.Repository as ghrepository
import github.Issue as ghissue

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString, PlainScalarString
from ruamel.yaml.comments import CommentedSeq

yaml = YAML(typ=["rt", "string"])


def comp_newline(a, b):
    """Compare a and b while normalising newlines."""

    if isinstance(a, str):
        a = a.replace("\r\n", "\n")
    if isinstance(b, str):
        b = b.replace("\r\n", "\n")

    return a == b


@dataclasses.dataclass(kw_only=True)
class Issue:
    """A limited representation of a Github issue."""

    number: int | None = None
    title: str | None = None
    body: str | None = None
    assignees: list[str] | None = None
    labels: list[str] | None = None

    def __post_init__(self):
        self.dirty: list = []

    def to_dict(self, yaml: bool = False, skip_missing: bool = False) -> dict:
        """Output the results to a dictionary.

        Parameters
        ----------
        yaml
            Wrap internal types for better serialisation by `ruamel.yaml`.

        Returns
        -------
        d
            The serialised data.
        """

        d = dataclasses.asdict(self)

        if skip_missing:
            d = {k: v for k, v in d.items() if v is not None}

        if yaml:
            # TODO: munge body
            for k, v in d.items():
                if isinstance(v, str):
                    if "\n" in v or len(v) > 80:
                        d[k] = LiteralScalarString(v)
                    else:
                        d[k] = PlainScalarString(v)
                if isinstance(v, list):
                    d[k] = CommentedSeq(v)
                    d[k].fa.set_flow_style()

        return d

    def _dirty_dict(self):
        """A dict of the dirty values."""
        return {k: v for k, v in self.to_dict().items() if k in self.dirty}

    def update(self, **kwargs) -> None:
        """Update the issue with the given fields and mark them dirty.

        Parameters
        ----------
        kwargs
            Updated values of the fields.
        """

        field_names = [f.name for f in dataclasses.fields(self)]

        for k, v in kwargs.items():
            if k not in field_names:
                continue

            existing_val = getattr(self, k, None)

            # See if the value has changed.
            # NOTE: we need to be careful with newlines here as Github sends \r\n
            if comp_newline(existing_val, v):
                # Nothing to update
                continue

            setattr(self, k, v)
            self.dirty.append(k)

    @classmethod
    def from_github(cls, issue: ghissue.Issue) -> "Issue":
        """Create the Issue from a github API issue.

        Parameters
        ----------
        issue
            The Github API representation.

        Returns
        -------
        Issue
            The converted issue.
        """
        assignees = [a.login for a in issue.assignees]
        labels = [l.name for l in issue.labels]

        return cls(
            number=issue.number,
            title=issue.title,
            body=issue.body,
            assignees=assignees,
            labels=labels,
        )

    @classmethod
    def list_to_yaml(cls, issues: list["Issue"]) -> CommentedSeq:
        """Convert a list of issues into a nicely formatted representation."""

        s = [issue.to_dict(yaml=True) for issue in issues]
        s = CommentedSeq(s)

        # Improve the formatting by adding newlines between issues
        for i in range(1, len(s)):
            s.yaml_set_comment_before_after_key(i, before="\n")

        return s


_gh: github.Github | None = None


def gh() -> github.Github:
    """Get a Github API handle."""

    global _gh

    if _gh is None:
        # Try and get an access token from the gh client
        token = subprocess.check_output("gh auth token", shell=True).decode()[:-1]
        _gh = github.Github(token)

    return _gh


def current_repo() -> str:
    """Get the current repo"""

    repo_name = subprocess.check_output("gh repo view --json nameWithOwner", shell=True)
    repo_name = json.loads(repo_name)["nameWithOwner"]

    return repo_name


def resolve_repo(repo: str | None) -> ghrepository.Repository:
    """Resolve a repo string to an API object.

    Parameters
    ----------
    repo
        Repository name to resolve. If not set, then try to find one from the current
        directory.

    Returns
    -------
    ghrepo
        Github API repository object.
    """

    if repo is None:
        repo = current_repo()

    return gh().get_repo(repo)


@click.group
def cli():
    """A command for synchronizing issues to and from a local YAML file."""
    pass


@click.argument("output", type=click.Path(dir_okay=False, path_type=Path))
@click.option(
    "--repo",
    help=(
        "The name of the repo as <owner>/<reponame>. "
        "If not given the current directory is mapped to an enclosing repository."
    ),
    default=None,
    type=str,
)
@cli.command()
def pull(output: Path, repo: str):
    """Fetch the issues and save as yaml into OUTPUT."""

    repo = resolve_repo(repo)

    gh_issues = repo.get_issues()

    issues = [Issue.from_github(issue) for issue in gh_issues]

    with open(output, "w") as fh:
        yaml_issue_list = Issue.list_to_yaml(issues)

        yaml.dump(yaml_issue_list, stream=fh)


@click.argument("input", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--repo",
    help=(
        "The name of the repo as <owner>/<reponame>. "
        "If not given the current directory is mapped to an enclosing repository."
    ),
    default=None,
    type=str,
)
@click.option(
    "-n",
    "--dry-run",
    help="Don't apply changes just simulate the actions.",
    is_flag=True,
)
@click.option(
    "--update-input/--no-update-input",
    help="Update the input file with the created issue numbers.",
    default=True,
)
@cli.command()
def push(input: Path, repo: str, dry_run: bool, update_input: bool):
    """Add and update issues from the INPUT file into a Github repository.

    INPUT must be a yaml formatted file.

    Any issue without a `number` field are presumed to be new and will be added to the
    repository. Unless overridden with the `--no-update-input` option the input file
    will be updated with the new issue numbers.

    The issue `title` is a required field. An optional text `body` can given for the
    main issue body, as can lists of names of `assignees` and string `labels` (which
    will be created if they don't exist already).
    """

    with open(input, "r") as fh:
        issues = yaml.load(fh)

    repo = resolve_repo(repo)

    new_issues_added = False

    for issue in issues:
        # If number is in there the issue currently exists
        if "number" in issue:
            gh_issue = repo.get_issue(int(issue["number"]))
            existing_issue = Issue.from_github(gh_issue)

            existing_issue.update(**issue)

            if not existing_issue.dirty:
                continue

            click.echo(f"=== Updating existing issue (#{existing_issue.number}) ===")
            click.echo("Changes:")
            click.echo(yaml.dumps(existing_issue._dirty_dict()))
            click.echo("")

            if not dry_run:
                gh_issue.edit(**existing_issue._dirty_dict())
                click.echo("Updated.")
            else:
                click.echo("Not updated (dry run).")
            click.echo("")

        else:
            new_issue = Issue(**issue)

            if new_issue.title is None:
                raise click.UsageError("All issues must have a title.")

            click.echo(f"=== Adding new issue ===")
            click.echo(yaml.dumps(new_issue.to_dict(yaml=True, skip_missing=True)))
            click.echo("")

            if not dry_run:
                gh_issue = repo.create_issue(**new_issue.to_dict(skip_missing=True))
                issue_number = gh_issue.number
                issue.insert(0, "number", issue_number)
                click.echo(f"Added (#{issue_number}).")
                new_issues_added = True
            else:
                click.echo(f"Not added (dry run).")
            click.echo("")

    if new_issues_added:
        if update_input:
            click.echo("=== Updating input file ===")
            with open(input, "w") as fh:
                yaml.dump(issues, stream=fh)
        else:
            click.echo("=== Not updating input file. UPDATE MANUALLY ===")


if __name__ == "__main__":
    cli()
