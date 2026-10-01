"""The Bash lexer: command splitting, quoting, nested commands, redirections."""

from __future__ import annotations

import pytest

from crew.agents.shellparse import ShellParseError, parse


def words(src: str) -> list[list[str]]:
    return [[w.text for w in c.words] for c in parse(src).commands]


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("ls -la", [["ls", "-la"]]),
        ("a && b || c; d | e & f", [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]),
        ("a\nb", [["a"], ["b"]]),
        ("a \\\n b", [["a", "b"]]),
        ("(a; b)", [["a"], ["b"]]),
        ("echo 'a && b' \"c; d\"", [["echo", "a && b", "c; d"]]),
        ('echo "a\\"b"', [["echo", 'a"b']]),
        ("echo a\\ b", [["echo", "a b"]]),
        ("g\\it commit", [["git", "commit"]]),
        ("'git' \"commit\"", [["git", "commit"]]),
        ("echo ''", [["echo", ""]]),
        ("ls # comment; rm x", [["ls"]]),
        ("echo a#b", [["echo", "a#b"]]),
        ("", []),
        ("   \n\n ", []),
    ],
)
def test_splitting_and_quoting(src: str, expected: list[list[str]]) -> None:
    assert words(src) == expected


def test_dynamic_words_are_flagged() -> None:
    cmds = parse("rm $X ${Y} $1 $(echo z) `w` plain 'single $Z'").commands
    flags = {w.text: w.dynamic for w in cmds[0].words}
    assert flags["$X"] and flags["${Y}"] and flags["$1"] and flags["$(...)"] and flags["`...`"]
    assert not flags["plain"]
    assert flags["single $Z"] is False  # single quotes are literal


def test_nested_commands_are_extracted() -> None:
    parsed = parse('echo $(git push) `rm -rf /` "$(curl x)" <(cat a) ${V:-$(whoami)}')
    assert sorted(parsed.nested) == sorted(["git push", "rm -rf /", "curl x", "cat a", "whoami"])


def test_nested_parentheses_and_quotes() -> None:
    parsed = parse('echo $(echo ")" $(date))')
    assert parsed.nested == ['echo ")" $(date)']


def test_ansi_c_quoting_is_dynamic() -> None:
    word = parse("rm $'\\x2e\\x2e'").commands[0].words[1]
    assert word.dynamic


def test_redirections() -> None:
    cmd = parse("cmd > out.txt 2>&1 >> log < in 2> err &> both >&2").commands[0]
    assert [w.text for w in cmd.words] == ["cmd"]
    ops = [(r.op, r.target.text if r.target else None, r.writes) for r in cmd.redirects]
    assert ops == [
        (">", "out.txt", True),
        (">&", "1", False),
        (">>", "log", True),
        ("<", "in", False),
        (">", "err", True),
        ("&>", "both", True),
        (">&", "2", False),
    ]


def test_redirect_to_file_via_dup_operator_writes() -> None:
    cmd = parse("cmd >&out.txt").commands[0]
    assert cmd.redirects[0].writes


def test_digit_word_is_not_swallowed_when_not_fd() -> None:
    assert words("echo 2 > f") == [["echo", "2"]]
    assert words("echo a2>f") == [["echo", "a2"]]


def test_heredoc_body_is_data_when_quoted() -> None:
    parsed = parse("cat <<'EOF' > f\n$(git push)\nrm -rf /\nEOF\nls")
    assert [[w.text for w in c.words] for c in parsed.commands] == [["cat"], ["ls"]]
    assert parsed.nested == []


def test_heredoc_body_expands_when_unquoted() -> None:
    parsed = parse("cat <<EOF\n$(git push)\nEOF\nls")
    assert parsed.nested == ["git push"]
    assert [[w.text for w in c.words] for c in parsed.commands] == [["cat"], ["ls"]]


def test_heredoc_with_tab_stripping() -> None:
    parsed = parse("cat <<-EOF\n\thello\n\tEOF\nls")
    assert [[w.text for w in c.words] for c in parsed.commands] == [["cat"], ["ls"]]


@pytest.mark.parametrize(
    "src",
    ["echo 'abc", 'echo "abc', "echo $(ls", "echo `ls", "echo ${A", "cat >", "echo $'a", "echo $(echo (a)"],
)
def test_unterminated_input_raises(src: str) -> None:
    with pytest.raises(ShellParseError):
        parse(src)
